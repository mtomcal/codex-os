// Exercise the desktop entry point against the actual fleet CLI and sanitized native history.
const assert = require("node:assert/strict");
const {spawnSync} = require("node:child_process");
const {copyFileSync, cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync} = require("node:fs");
const {tmpdir} = require("node:os");
const {join} = require("node:path");
const fixture = require("./fixtures/desktop-worker-history.json");

const source = join(__dirname, "..");
const workerDispatch = eval(readFileSync(join(source, "dispatch-worker.js"), "utf8"));
const reply = data => ({content: [{type: "text", text: JSON.stringify(data)}]});
const coordinator = "11111111-1111-4111-8111-111111111111";
const worker = fixture.detail.thread.id;
const second = "44444444-4444-4444-8444-444444444444";
const {projectId, path: projectPath, hostId} = fixture.projects.projects[0];

async function run(root) {
    for (const name of readdirSync(source).filter(name => name.endsWith(".py"))) {
        copyFileSync(join(source, name), join(root, name));
    }
    cpSync(join(source, "templates"), join(root, "templates"), {recursive: true});
    const cli = (cwd, ...args) => {
        const result = spawnSync("python3", [join(root, "codexos.py"), ...args], {cwd, encoding: "utf8"});
        assert.equal(result.status, 0, result.stderr);
        return JSON.parse(result.stdout);
    };
    cli(root, "init");
    const directory = join(root, "bots", "chief-of-staff");
    const manifest = join(directory, "bot.json");
    writeFileSync(manifest, JSON.stringify({...JSON.parse(readFileSync(manifest)), primary_thread: coordinator}));

    const objective = "Verify the parser's empty-input result";
    const scope = "Parser files only";
    const request = {objective, scope, projectId, projectPath, hostId,
        brief: "Run the focused check and end after recording the result."};
    const ledger = (...args) => cli(directory, "dispatch", ...args);
    const show = key => ledger("show", key);
    const launches = [];
    let candidates = [];
    let detailChanges = {};
    let currentChat = coordinator;
    const desktop = {
        async exec_command({cmd, workdir}) {
            assert.equal(workdir, directory);
            assert.match(cmd, /^python3 (-c |\.\.\/\.\.\/codexos\.py dispatch )/);
            const result = spawnSync("sh", ["-c", cmd], {
                cwd: workdir, encoding: "utf8", env: {...process.env, CODEX_THREAD_ID: currentChat},
            });
            return {exit_code: result.status, output: result.stdout || result.stderr};
        },
        async mcp__codex_app__list_projects() {
            return reply(fixture.projects);
        },
        async mcp__codex_app__list_threads({mode, hostId: host, archived}) {
            assert.equal(mode, "history");
            assert.equal(host, hostId);
            return reply({...fixture.history, threads: archived ? [] : candidates});
        },
        async mcp__codex_app__read_thread({threadId, hostId: host, includeOutputs}) {
            assert.equal(host, hostId);
            assert.equal(includeOutputs, true);
            const input = structuredClone(fixture.detail);
            input.thread = {...input.thread, id: threadId, ...detailChanges};
            const output = input.turns[0].items[0].output;
            output.text = output.text.replace("Sample assignment", launches.at(-1).prompt);
            output.originalChars = output.text.length;
            return reply(input);
        },
        async mcp__codex_app__create_thread(args) {
            launches.push(args);
            assert.deepEqual(args.target, {type: "project", projectId, environment: {type: "local"}});
            assert.match(args.prompt, /Verify the parser's empty-input result/);
            assert.ok(args.prompt.includes(request.brief));
            if (args.title.endsWith("denied")) return {isError: true, content: []};
            if (args.title.endsWith("interrupted")) throw Error("Fixture lost its native launch reply");
            if (args.title.endsWith("queued")) return reply({clientThreadId: "queued-reference"});
            if (args.title.endsWith("wrong-host")) return reply({threadId: worker, hostId: "other-host"});
            if (args.title.endsWith("primary")) return reply({threadId: coordinator, hostId});
            return reply({threadId: worker, hostId});
        },
    };
    const dispatch = (key, tools = desktop, overrides = {}) => workerDispatch(tools, directory, {key, ...request, ...overrides});

    currentChat = worker;
    await assert.rejects(dispatch("ready"), /registered coordinator chat/);
    assert.equal(launches.length, 0);
    currentChat = coordinator;

    const pending = await dispatch("ready", {...desktop, mcp__codex_app__create_thread: undefined});
    assert.equal(pending.blocker, "native_launch_unavailable");
    assert.equal(show("ready").launch_issued, 0);
    assert.equal(launches.length, 0);
    assert.equal((await dispatch("ready", desktop, {projectId: "wrong"})).blocker, "native_project_mismatch");
    assert.equal(launches.length, 0);

    assert.equal((await dispatch("ready")).worker, worker);
    assert.deepEqual([show("ready").worker, show("ready").host, show("ready").state], [worker, hostId, "running"]);
    assert.equal((await dispatch("ready", {exec_command: desktop.exec_command})).worker, worker);
    const revision = ledger("reserve", "parser-revision", "--reuse", "ready", "--objective", objective, "--scope", scope,
        "--requirement", "Include a whitespace case", "--required");
    assert.deepEqual([revision.parent, revision.worker, revision.host, revision.launch], ["ready", worker, hostId, false]);
    assert.equal(launches.length, 1);

    const plan = JSON.stringify([{id: "test", action: "Run check", target: "Parser project", required: true}]);
    ledger("reserve", "preflight", "--objective", objective, "--scope", scope, "--prepare", "--plan", plan);
    assert.equal((await dispatch("preflight")).blocker, "permission_preflight");
    assert.equal(show("preflight").launch_issued, 0);
    assert.equal(launches.length, 1);

    for (const key of ["denied", "wrong-host", "primary"]) {
        const before = launches.length;
        const result = await dispatch(key);
        assert.equal(result.blocker, key === "denied" ? "native_launch_failed_or_unconfirmed" : "native_launch_reply_mismatch");
        assert.equal(show(key).worker, null);
        assert.equal(show(key).launch_issued, 1);
        assert.equal((await dispatch(key)).blocker, "native_launch_unconfirmed");
        assert.equal(launches.length, before + 1);
    }

    const candidate = overrides => ({...fixture.history.threads[0], title: launches.at(-1).title, ...overrides});
    assert.equal((await dispatch("interrupted")).blocker, "native_launch_failed_or_unconfirmed");
    candidates = [candidate({id: second, projectId: "wrong"}), candidate({id: coordinator})];
    assert.equal((await dispatch("interrupted")).blocker, "native_launch_unconfirmed");
    candidates = [candidate({id: second})];
    detailChanges = {hostId: "other-host"};
    assert.equal((await dispatch("interrupted")).blocker, "native_launch_unconfirmed");
    assert.equal(show("interrupted").worker, null);
    detailChanges = {};
    candidates.push(candidate({}));
    assert.equal((await dispatch("interrupted")).blocker, "native_worker_ambiguous");
    assert.equal(show("interrupted").worker, null);
    candidates.pop();
    assert.equal((await dispatch("interrupted")).worker, second);
    assert.equal(launches.filter(args => args.title.endsWith("interrupted")).length, 1);

    candidates = [];
    const queued = await dispatch("queued");
    assert.equal(queued.clientThreadId, "queued-reference");
    assert.equal(queued.blocker, "native_worker_setup_pending");
    assert.equal(show("queued").worker, null);
    const queuedWorker = "55555555-5555-4555-8555-555555555555";
    candidates = [candidate({id: queuedWorker})];
    assert.equal((await dispatch("queued")).worker, queuedWorker);
    assert.equal(launches.filter(args => args.title.endsWith("queued")).length, 1);
}

const root = mkdtempSync(join(tmpdir(), "codexos-dispatch-worker-"));
run(root).catch(error => {
    console.error(error);
    process.exitCode = 1;
}).finally(() => rmSync(root, {recursive: true}));
