// Drive the actual desktop entry point with a small substitute for the native tools.
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const heartbeat = eval(readFileSync(join(__dirname, "../heartbeat.js"), "utf8"));
const reply = data => ({content: [{type: "text", text: JSON.stringify(data)}]});

function poll(job, status = "completed") {
    const active = status === "inProgress";
    return {
        thread: {id: job.worker, hostId: job.host, status: {type: active ? "active" : "idle"}},
        latestTurn: {id: "turn-" + job.key, status, completedAt: active ? null : 1795724059},
    };
}

async function checkMissedNotification() {
    const jobs = ["finished", "running", "unavailable"].map((key, index) => ({
        key, state: "running", host: index === 0 ? "durable" : "local", delivery: null,
        worker: `11111111-1111-4111-8111-11111111111${index}`,
    }));
    const [finished, running, unavailable] = jobs;
    const targets = jobs.map(({worker, host}) => ({threadId: worker, hostId: host}));
    let statusCalls = 0;
    let archiveCalls = 0;
    let result = reply({
        polls: [poll(running, "inProgress"), poll(finished)],
        errors: [{...targets[2], message: "No Codex thread found"}],
    });
    let candidates = jobs;
    const tools = {
        async exec_command({cmd}) {
            assert.equal(cmd, "python3 ../../codexos.py heartbeat");
            return {exit_code: 0, output: JSON.stringify({workers_to_check: candidates, workers_to_archive: []})};
        },
        async mcp__codex_app__wait_threads(args) {
            statusCalls++;
            assert.deepEqual(args, {targets, timeoutMs: 0});
            if (result instanceof Error) throw result;
            return result;
        },
        async mcp__codex_app__list_archived_threads() { archiveCalls++; },
        async mcp__codex_app__set_thread_archived() { archiveCalls++; },
    };
    let pulse = await heartbeat(tools);
    assert.equal(statusCalls, 1);
    assert.deepEqual(pulse.workers_to_review, [{...finished, turn_id: "turn-finished", turn_status: "completed"}]);
    assert.deepEqual(pulse.workers_to_check, jobs);

    for (const turnStatus of ["failed", "interrupted"]) {
        result = reply({polls: [poll(finished, turnStatus)]});
        pulse = await heartbeat(tools);
        assert.deepEqual(pulse.workers_to_review, [{...finished, turn_id: "turn-finished", turn_status: turnStatus}]);
    }
    const incomplete = poll(unavailable);
    incomplete.latestTurn.completedAt = null;
    const mismatched = [
        {...poll(finished), thread: {...poll(finished).thread, hostId: "local"}},
        {...poll(running), thread: {...poll(running).thread, id: finished.worker}},
        incomplete,
    ];
    for (const snapshot of [
        reply({polls: mismatched}),
        reply({polls: [{...poll(finished), activityComplete: false}]}),
        reply({activityComplete: false, polls: [poll(finished)]}),
        reply({polls: [poll(finished)], errors: [{...targets[0], message: "Status unavailable"}]}),
        {isError: true, content: []},
        Error("Native tool unavailable"),
    ]) {
        result = snapshot;
        pulse = await heartbeat(tools);
        assert.deepEqual(pulse.workers_to_review, []);
        assert.deepEqual(pulse.workers_to_check, jobs);
    }

    candidates = [{key: "reserved", state: "reserved", host: null, worker: null, delivery: null}];
    const callsBefore = statusCalls;
    pulse = await heartbeat(tools);
    assert.equal(statusCalls, callsBefore);
    assert.deepEqual(pulse.workers_to_check, candidates);
    assert.deepEqual(pulse.workers_to_review, []);
    assert.equal(archiveCalls, 0);
}

async function checkArchiveRecovery() {
    const worker = "11111111-1111-4111-8111-111111111111";
    const job = {worker, key: "trial", host: "local"};
    const delivered = {...job, state: "accepted", delivery: "Result posted"};
    let idle = false;
    let wrongHost = false;
    let archived = false;
    let cleaned = false;
    let archiveCalls = 0;
    const tools = {
        async exec_command({cmd}) {
            if (cmd === "python3 ../../codexos.py heartbeat") {
                return {exit_code: 0, output: cleaned ? "" : JSON.stringify({workers_to_check: [delivered], workers_to_archive: [job]})};
            }
            assert.equal(cmd, "python3 ../../codexos.py dispatch cleaned trial --evidence 'Confirmed in native local archive: " + worker + "'");
            assert.ok(archived);
            cleaned = true;
            return {exit_code: 0, output: "{}"};
        },
        async mcp__codex_app__wait_threads(args) {
            assert.deepEqual(args, {targets: [{threadId: worker, hostId: "local"}], timeoutMs: 0});
            return reply({polls: [poll({...job, host: wrongHost ? "durable" : "local"}, idle ? "completed" : "inProgress")]});
        },
        async mcp__codex_app__list_archived_threads() {
            return reply({threads: archived ? [{id: worker, hostId: "local"}] : [], nextCursor: null});
        },
        async mcp__codex_app__set_thread_archived(args) {
            assert.deepEqual(args, {threadId: worker, hostId: "local", archived: true});
            archiveCalls++;
            archived = true;
            throw Error("Lost acknowledgement after archive");
        },
    };
    assert.deepEqual((await heartbeat(tools)).workers_to_review, []);
    assert.equal(archiveCalls, 0);
    idle = true;
    wrongHost = true;
    await heartbeat(tools);
    assert.equal(archiveCalls, 0);
    wrongHost = false;
    await heartbeat(tools);
    assert.ok(!cleaned);
    await heartbeat(tools);
    assert.ok(cleaned);
    await heartbeat(tools);
    assert.equal(archiveCalls, 1);
}

(async () => {
    await checkMissedNotification();
    await checkArchiveRecovery();
})().catch(error => { console.error(error); process.exitCode = 1; });
