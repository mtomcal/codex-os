// Drive the actual desktop entry point with a small substitute for the native tools.
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const heartbeat = eval(readFileSync(join(__dirname, "../heartbeat.js"), "utf8"));

async function check() {
    const worker = "11111111-1111-4111-8111-111111111111";
    const job = {worker, key: "trial", host: "local"};
    let idle = false;
    let archived = false;
    let cleaned = false;
    let archiveCalls = 0;
    const reply = data => ({content: [{text: JSON.stringify(data)}]});
    const tools = {
        async exec_command({cmd}) {
            if (cmd === "python3 ../../codexos.py heartbeat") {
                return {exit_code: 0, output: cleaned ? "" : JSON.stringify({workers_to_check: [job], workers_to_archive: [job]})};
            }
            assert.equal(cmd, "python3 ../../codexos.py dispatch cleaned trial --evidence 'Confirmed in native local archive: " + worker + "'");
            assert.ok(archived);
            cleaned = true;
            return {exit_code: 0, output: "{}"};
        },
        async mcp__codex_app__wait_threads() {
            return reply({polls: [{thread: {id: worker, status: {type: idle ? "idle" : "active"}},
                latestTurn: {status: idle ? "completed" : "inProgress"}}]});
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
    await heartbeat(tools);
    assert.equal(archiveCalls, 0);
    idle = true;
    await heartbeat(tools);
    assert.ok(!cleaned);
    await heartbeat(tools);
    assert.ok(cleaned);
    await heartbeat(tools);
    assert.equal(archiveCalls, 1);
}
check().catch(error => { console.error(error); process.exitCode = 1; });
