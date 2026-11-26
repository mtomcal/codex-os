// Replay the coordinator workflow against the real CLI and a native chat fixture.
const assert = require("node:assert/strict");
const {spawnSync} = require("node:child_process");
const {copyFileSync, cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync} = require("node:fs");
const {tmpdir} = require("node:os");
const {join} = require("node:path");

const source = join(__dirname, "..");
const heartbeat = eval(readFileSync(join(source, "heartbeat.js"), "utf8"));
const reply = data => ({content: [{type: "text", text: JSON.stringify(data)}]});
const readReply = result => JSON.parse(result.content[0].text);

async function replay(root) {
    for (const name of readdirSync(source).filter(name => name.endsWith(".py"))) {
        copyFileSync(join(source, name), join(root, name));
    }
    cpSync(join(source, "templates"), join(root, "templates"), {recursive: true});
    const run = (cwd, args) => spawnSync("python3", [join(root, "codexos.py"), ...args], {cwd, encoding: "utf8"});
    const init = run(root, ["init"]);
    assert.equal(init.status, 0, init.stderr);
    const project = join(root, "bots", "chief-of-staff");
    const dispatch = (...args) => {
        const result = run(project, ["dispatch", ...args]);
        assert.equal(result.status, 0, result.stderr);
        return JSON.parse(result.stdout);
    };
    const reject = (error, ...args) => {
        const result = run(project, ["dispatch", ...args]);
        assert.equal(result.status, 1, `Expected rejection for ${args.join(" ")}. ${result.stdout || result.stderr}`);
        assert.match(result.stderr, error);
    };

    const parent = "parser-fix";
    const key = "parser-whitespace";
    const requirement = "Include a whitespace-only input case with an empty result";
    const target = {threadId: "11111111-1111-4111-8111-111111111111", hostId: "local"};
    const original = {id: "original-turn", status: "inProgress", items: []};
    const followup = {id: "revised-turn", status: "inProgress", items: []};
    const turns = [original];
    const thread = () => ({id: target.threadId, hostId: target.hostId,
        status: {type: turns[0].status === "inProgress" ? "active" : "idle"}});
    let queued;
    let launches = 0;
    let sends = 0;
    const tools = {
        async exec_command({cmd, workdir}) {
            assert.equal(cmd, "python3 ../../codexos.py heartbeat");
            const result = run(workdir, ["heartbeat"]);
            return {exit_code: result.status, output: result.stdout || result.stderr};
        },
        async mcp__codex_app__create_thread({prompt}) {
            launches++;
            original.items.push({type: "userMessage", id: "original-assignment", content: [{type: "text", text: prompt}]});
            return reply(target);
        },
        async mcp__codex_app__wait_threads(args) {
            assert.equal(args.timeoutMs, 0);
            return reply({polls: args.targets.some(job => job.threadId === target.threadId && job.hostId === target.hostId)
                ? [{thread: thread(), latestTurn: turns[0]}] : []});
        },
        async mcp__codex_app__send_message_to_thread({prompt, ...destination}) {
            sends++;
            assert.deepEqual(destination, target);
            queued = {type: "userMessage", id: "revision-message", content: [{type: "text", text: prompt}]};
            throw Error("Fixture lost its send receipt");
        },
        async mcp__codex_app__read_thread(destination) {
            assert.deepEqual(destination, target);
            return reply({thread: thread(), turns});
        },
    };
    const pulse = () => heartbeat(tools, project);

    const objective = "Exercise the parser's empty-input behavior";
    const scope = "Parser input cases only";
    assert.equal(dispatch("reserve", parent, "--objective", objective, "--scope", scope).launch, true);
    const worker = readReply(await tools.mcp__codex_app__create_thread({prompt: `${parent}. ${objective}. ${scope}.`}));
    dispatch("bind", parent, worker.threadId, "--host", worker.hostId);
    assert.deepEqual((await pulse()).workers_to_review, []);
    const active = readReply(await tools.mcp__codex_app__read_thread(target));
    assert.equal(active.thread.status.type, "active");
    assert.equal(active.turns[0].status, "inProgress");

    const sendPlan = JSON.stringify([{id: "send-revision", action: "Send the revision",
        target: target.threadId, required: true}]);
    const reserve = ["reserve", key, "--reuse", parent, "--objective", objective,
        "--requirement", requirement, "--required"];
    reject(/exact objective and scope/, ...reserve, "--scope", "Parser and deployment");
    const reuse = dispatch(...reserve, "--scope", scope, "--plan", sendPlan, "--prepare");
    assert.deepEqual([reuse.launch, reuse.parent, reuse.host, reuse.worker], [false, parent, target.hostId, target.threadId]);
    const claim = ["handoff", key, "--claim", "Fixture operator authorized a message to this worker"];
    reject(/permissions are pending/, ...claim);
    dispatch("permissions", key, "--decisions", JSON.stringify({
        "send-revision": {decision: "approved", evidence: claim[3]},
    }));
    assert.equal(dispatch(...claim).send, true);
    await assert.rejects(tools.mcp__codex_app__send_message_to_thread({
        ...target, prompt: `${parent} / ${key}. ${requirement}. Acknowledge both keys and report the revised cases.`,
    }), /lost its send receipt/);
    assert.equal(dispatch(...claim).send, false);
    assert.equal((await pulse()).pending_handoffs[0].handoff, "sending");
    const acknowledgement = (worker = target.threadId, host = target.hostId) => [
        "handoff", key, "--acknowledged", "Worker item adopted-revision",
        "--worker", worker, "--host", host, "--turn", followup.id,
    ];
    reject(/requires a confirmed send/, ...acknowledgement());

    const stale = "original-cases.json";
    writeFileSync(join(project, stale), JSON.stringify([{input: "", expected: ""}]));
    Object.assign(original, {status: "completed", completedAt: 1});
    assert.equal((await pulse()).workers_to_review[0].turn_id, original.id);
    reject(/await worker acknowledgement/, "report", parent, "--evidence", stale, "--covers", key);
    assert.equal(dispatch("show", parent).state, "running");

    // The native fixture starts the queued follow-up in the same chat after the first turn.
    followup.items.push(queued);
    turns.unshift(followup);
    const observedRevision = readReply(await tools.mcp__codex_app__read_thread(target));
    assert.deepEqual([observedRevision.thread.id, observedRevision.thread.hostId], [target.threadId, target.hostId]);
    const [message] = observedRevision.turns[0].items;
    assert.ok([parent, key, requirement].every(text => message.content[0].text.includes(text)));
    dispatch("handoff", key, "--sent", `Native item ${message.id} in ${followup.id}`);
    assert.equal((await pulse()).pending_handoffs[0].handoff, "sent");
    reject(/await worker acknowledgement/, "report", parent, "--evidence", stale, "--covers", key);

    followup.items.push({type: "agentMessage", id: "adopted-revision",
        text: `I will apply ${parent} / ${key} to the parser cases.`});
    const observedAck = readReply(await tools.mcp__codex_app__read_thread(target));
    const ack = observedAck.turns[0].items[1];
    assert.equal(ack.type, "agentMessage");
    assert.ok(ack.text.includes(`${parent} / ${key}`));
    reject(/exact bound worker/, ...acknowledgement("wrong-chat"));
    reject(/exact bound worker/, ...acknowledgement(target.threadId, "wrong-host"));
    const receipt = dispatch(...acknowledgement());
    assert.equal(receipt.acknowledgement_turn, observedAck.turns[0].id);
    assert.equal(receipt.acknowledgement, `Worker item ${ack.id}`);
    assert.deepEqual(dispatch(...acknowledgement()), receipt);
    assert.deepEqual((await pulse()).pending_handoffs, []);
    assert.equal(dispatch(...reserve, "--scope", scope).launch, false);
    assert.equal(dispatch(...claim).send, false);
    reject(/exactly these required handoffs/, "report", parent, "--evidence", stale);
    assert.deepEqual((await pulse()).workers_to_review, []);

    const revised = "revised-cases.json";
    const whitespace = {input: " \t", expected: ""};
    writeFileSync(join(project, revised), JSON.stringify([{input: "", expected: ""}, whitespace]));
    followup.items.push({type: "agentMessage", id: "revised-result", text: `Completed ${parent} / ${key} in ${revised}.`});
    Object.assign(followup, {status: "completed", completedAt: 2});
    assert.equal((await pulse()).workers_to_review[0].turn_id, followup.id);
    const observedResult = readReply(await tools.mcp__codex_app__read_thread(target)).turns[0].items[2];
    assert.ok(observedResult.text.includes(`${parent} / ${key} in ${revised}`));
    assert.equal(dispatch("report", parent, "--evidence", revised, "--covers", key).report, revised);
    assert.ok(!JSON.parse(readFileSync(join(project, stale))).some(test => test.input === whitespace.input));
    assert.deepEqual(JSON.parse(readFileSync(join(project, revised))).find(test => test.input === whitespace.input), whitespace);
    const accept = ["review", parent, "--decision", "accept", "--evidence", `Verified whitespace case in ${revised}`];
    reject(/exactly these required handoffs/, ...accept);
    assert.equal(dispatch(...accept, "--verified", key).state, "accepted");

    const plan = JSON.stringify([{id: "deploy", action: "Run deploy", target: "Deployment fixture", required: true}]);
    const independent = ["reserve", "deployment", "--objective", "Deploy the parser", "--scope", "Deployment fixture"];
    assert.equal(dispatch(...independent, "--plan", plan, "--prepare").permissions.status, "pending");
    assert.equal(dispatch(...independent).launch, false);
    assert.equal(dispatch(...independent, "--decisions",
        JSON.stringify({deploy: {decision: "approved", evidence: "Separate fixture operator grant"}})).launch, true);

    dispatch("bind", "deployment", "22222222-2222-4222-8222-222222222222", "--host", "local");
    const denied = "deployment-config";
    assert.equal(dispatch("reserve", denied, "--reuse", "deployment", "--objective", "Deploy the parser",
        "--scope", "Deployment fixture", "--requirement", "Use the current deployment configuration", "--required").launch, false);
    const claimDenied = ["handoff", denied, "--claim", "Fixture authorization subject to native decision"];
    assert.equal(dispatch(...claimDenied).send, true);
    const denial = ["handoff", denied, "--denied", "Fixture native tool denied the send"];
    assert.deepEqual(dispatch(...denial), dispatch(...denial));
    assert.equal(dispatch("show", denied).send_denial, denial[3]);
    assert.equal(dispatch(...claimDenied).send, false);
    reject(/native send was denied/, "handoff", denied, "--reset", "Attempt to reopen");
    assert.equal((await pulse()).pending_handoffs[0].key, denied);
    reject(/await worker acknowledgement/, "report", "deployment", "--evidence", "Original deployment", "--covers", denied);

    assert.equal(dispatch("delivered", parent, "--evidence", revised).delivery, revised);
    assert.equal(dispatch(...reserve, "--scope", scope).launch, false);
    assert.deepEqual([launches, sends], [1, 1]);
}

const root = mkdtempSync(join(tmpdir(), "dispatch-resteering-"));
replay(root).catch(error => {
    console.error(error);
    process.exitCode = 1;
}).finally(() => rmSync(root, {recursive: true}));
