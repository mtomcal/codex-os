// Drive the actual desktop entry point with a small substitute for the native tools.
const assert = require("node:assert/strict");
const {spawnSync} = require("node:child_process");
const {copyFileSync, cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync} = require("node:fs");
const {tmpdir} = require("node:os");
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

async function checkActiveWorkerDrift() {
    const root = mkdtempSync(join(tmpdir(), "codexos-worker-drift-"));
    try {
        for (const file of readdirSync(join(__dirname, "..")).filter(name => name.endsWith(".py"))) {
            copyFileSync(join(__dirname, "..", file), join(root, file));
        }
        cpSync(join(__dirname, "../templates"), join(root, "templates"), {recursive: true});
        const project = join(root, "bots", "chief-of-staff");
        function dispatch(...args) {
            return readResult(spawnSync("python3", ["codexos.py", ...args], {cwd: root, encoding: "utf8"}));
        }
        function readResult(result) {
            assert.equal(result.status, 0, result.stderr);
            return result.stdout.trim() ? JSON.parse(result.stdout) : null;
        }
        function rejected(error, ...args) {
            const result = spawnSync("python3", ["codexos.py", "dispatch", ...args], {cwd: root, encoding: "utf8"});
            assert.notEqual(result.status, 0);
            assert.match(result.stderr, error);
        }
        dispatch("init");
        const job = {key: "parser-fixture", worker: "11111111-1111-4111-8111-111111111111", host: "local"};
        const target = {threadId: job.worker, hostId: job.host};
        const correction = "Run the parser against synthetic-fixture and retain its result.";
        assert.equal(dispatch("dispatch", "reserve", job.key, "--objective", "Verify the parser output",
            "--scope", "Run the parser with synthetic-fixture only").launch, true);
        dispatch("dispatch", "monitor", job.key, "--expected", "synthetic-fixture", "--correction", correction);
        dispatch("dispatch", "bind", job.key, job.worker, "--host", job.host);

        const active = poll(job, "inProgress");
        let status = reply({polls: [active]});
        const thread = {...active.thread};
        const turn = {...active.latestTurn, items: []};
        const checkpoint = (id, text) => turn.items.push({id, type: "agentMessage", phase: "commentary", text});
        let sends = 0;
        let readUnavailable = false;
        const tools = {
            async exec_command({cmd, workdir}) {
                assert.equal(workdir, project);
                const result = spawnSync(cmd, {cwd: project, encoding: "utf8", shell: true});
                return {exit_code: result.status, output: result.status ? result.stderr : result.stdout};
            },
            async mcp__codex_app__wait_threads(args) {
                assert.deepEqual(args, {targets: [target], timeoutMs: 0});
                return status;
            },
            async mcp__codex_app__read_thread({threadId, hostId, turnLimit, itemLimit, includeOutputs, maxOutputCharsPerItem}) {
                assert.deepEqual({threadId, hostId}, target);
                assert.deepEqual([turnLimit, itemLimit, includeOutputs, maxOutputCharsPerItem], [1, 20, false, 220]);
                if (readUnavailable) return {isError: true, content: []};
                return reply({schemaVersion: 1, thread, turns: [turn]});
            },
            async mcp__codex_app__create_thread() { assert.fail("The correction must reuse the bound worker"); },
            async mcp__codex_app__send_message_to_thread({threadId, hostId, prompt}) {
                assert.deepEqual({threadId, hostId}, target);
                assert.ok(prompt.includes(correction));
                sends++;
                return reply({threadId, hostId});
            },
        };
        const tick = () => heartbeat(tools, project);
        assert.equal((await tick()).worker_checkpoints, undefined);
        checkpoint("msg-healthy", "CodexOS checkpoint parser-fixture synthetic-fixture");
        assert.equal((await tick()).worker_checkpoints, undefined);
        checkpoint("msg-unrelated", "CodexOS checkpoint other-dispatch staging-fixture");
        turn.items.push({id: "msg-user", type: "userMessage",
            content: [{type: "text", text: "CodexOS checkpoint parser-fixture staging-fixture"}]});
        assert.equal((await tick()).worker_checkpoints, undefined);
        checkpoint("msg-drift", "CodexOS checkpoint parser-fixture staging-fixture");

        status = reply({polls: [poll({...job, host: "elsewhere"}, "inProgress")]});
        assert.equal((await tick()).worker_checkpoints, undefined);
        status = reply({polls: [active]});
        thread.id = "wrong-chat";
        assert.equal((await tick()).worker_checkpoints, undefined);
        thread.id = job.worker;
        turn.id = "old-turn";
        assert.equal((await tick()).worker_checkpoints, undefined);
        turn.id = active.latestTurn.id;
        readUnavailable = true;
        assert.equal((await tick()).worker_status_pending, true);
        readUnavailable = false;
        assert.equal(dispatch("dispatch", "show", job.key).additions, undefined);

        const [drift] = (await tick()).worker_checkpoints ?? [];
        assert.equal(drift?.status, "drift");
        assert.deepEqual([drift.parent, drift.expected, drift.observed, drift.evidence], [
            job.key, "synthetic-fixture", "staging-fixture", "Codex turn turn-parser-fixture, item msg-drift",
        ]);
        const key = drift.key;
        const stale = "staging-result.json";
        writeFileSync(join(project, stale), JSON.stringify({fixture: "staging-fixture", parsed: 99}));
        const [pending] = (await tick()).pending_handoffs;
        assert.deepEqual([pending.key, pending.host, pending.worker, pending.handoff], [key, job.host, job.worker, "pending"]);
        assert.equal((await tick()).worker_checkpoints, undefined);
        rejected(/await worker acknowledgement/, "report", job.key, "--evidence", stale, "--covers", key);
        const authorization = "Fixture operator authorized this correction to the bound worker";
        rejected(/permissions are pending/, "handoff", key, "--claim", authorization);
        assert.equal(sends, 0);

        dispatch("dispatch", "permissions", key, "--decisions", JSON.stringify({
            "send-correction": {decision: "approved", evidence: authorization},
        }));
        const claim = dispatch("dispatch", "handoff", key, "--claim", authorization);
        assert.equal(claim.send, true);
        assert.equal(dispatch("dispatch", "handoff", key, "--claim", authorization).send, false);
        const prompt = `${job.key} / ${key}. ${claim.requirement}`;
        await tools.mcp__codex_app__send_message_to_thread({
            threadId: claim.worker, hostId: claim.host, prompt,
        });
        assert.equal((await tick()).pending_handoffs[0].handoff, "sending");
        assert.equal(sends, 1);
        dispatch("dispatch", "handoff", key, "--sent", "Native item msg-correction in turn-after-correction");
        checkpoint("msg-uncorrelated", "CodexOS checkpoint parser-fixture synthetic-fixture");
        assert.equal((await tick()).worker_checkpoints, undefined);

        active.latestTurn.id = "turn-after-correction";
        status = reply({polls: [active]});
        turn.id = active.latestTurn.id;
        const corrected = "synthetic-result.json";
        writeFileSync(join(project, corrected), JSON.stringify({fixture: "synthetic-fixture", parsed: 17}));
        turn.items = [{id: "msg-correction", type: "userMessage", content: [{type: "text", text: prompt}]}];
        checkpoint("msg-corrected", `CodexOS checkpoint parser-fixture synthetic-fixture ${key}`);
        assert.equal((await tick()).worker_checkpoints, undefined);
        const observed = JSON.parse((await tools.mcp__codex_app__read_thread({
            ...target, turnLimit: 1, itemLimit: 20, includeOutputs: false, maxOutputCharsPerItem: 220,
        })).content[0].text);
        const [message, applied] = observed.turns[0].items;
        assert.ok(message.content[0].text.includes(key));
        assert.equal(applied.type, "agentMessage");
        assert.ok(applied.text.includes(key));
        dispatch("dispatch", "handoff", key, "--acknowledged", `Worker item ${applied.id}`,
            "--host", observed.thread.hostId, "--worker", observed.thread.id, "--turn", observed.turns[0].id);
        const [recovery] = (await tick()).worker_checkpoints;
        assert.deepEqual(recovery, {parent: job.key, key, status: "recovered",
            evidence: "Codex turn turn-after-correction, item msg-corrected"});
        assert.equal((await tick()).worker_checkpoints, undefined);
        const open = dispatch("dispatch", "show", job.key);
        assert.equal(open.state, "running");
        assert.equal(open.worker, job.worker);
        assert.equal(open.checkpoint.recovery, recovery.evidence);
        assert.deepEqual(open.additions.map(addition => addition.key), [key]);
        assert.deepEqual(dispatch("dispatch", "list", "--active").map(row => row.worker), [job.worker]);
        assert.equal(sends, 1);

        status = reply({polls: [{...poll(job), latestTurn: {...turn, status: "completed", completedAt: 1795724060}}]});
        assert.equal((await tick()).workers_to_review[0].turn_id, turn.id);
        dispatch("dispatch", "report", job.key, "--evidence", corrected, "--covers", key);
        const accept = ["review", job.key, "--decision", "accept", "--evidence", "Verified synthetic-result.json"];
        rejected(/exactly these required handoffs/, ...accept);
        assert.deepEqual(JSON.parse(readFileSync(join(project, corrected))), {fixture: "synthetic-fixture", parsed: 17});
        assert.equal(dispatch("dispatch", ...accept, "--verified", key).state, "accepted");
    } finally {
        rmSync(root, {recursive: true, force: true});
    }
}

(async () => {
    await checkActiveWorkerDrift();
    await checkMissedNotification();
    await checkArchiveRecovery();
})().catch(error => { console.error(error); process.exitCode = 1; });
