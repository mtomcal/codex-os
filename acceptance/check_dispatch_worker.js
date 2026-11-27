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
    let competingWorker = worker;
    let changeCompetingDetail;
    let changeCompetingItems;
    let pageCompetingHistory = false;
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
        async mcp__codex_app__read_thread({threadId, hostId: host, includeOutputs, cursor, itemCursor}) {
            assert.equal(host, hostId);
            assert.equal(includeOutputs, true);
            const detail = structuredClone(fixture.detail);
            detail.thread.id = threadId;
            detail.thread.title = launches.at(-1).title;
            detail.thread.cwd = candidates.find(chat => chat.id === threadId).cwd;
            const [turn] = detail.turns;
            const [initialItem] = turn.items;
            initialItem.output.text = initialItem.output.text.replace("Sample assignment", launches.at(-1).prompt);
            if (threadId !== competingWorker) return reply(detail);

            if (pageCompetingHistory) {
                initialItem.output.text = initialItem.output.text.replace("Parser files only", "Other scope");
                if (itemCursor === "older-items") {
                    const items = {...fixture.itemPage, items: [initialItem]};
                    changeCompetingItems?.(items);
                    return reply(items);
                }
                turn.items = [{type: "agentMessage"}];
                turn.nextItemCursor = "older-items";
                if (!cursor) {
                    turn.id = "newer-turn";
                    detail.page = {...detail.page, hasMore: true, nextCursor: "older-turn"};
                }
            }
            changeCompetingDetail?.(detail, cursor);
            return reply(detail);
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

    const unavailable = {...desktop, mcp__codex_app__create_thread: undefined};
    assert.equal((await dispatch("route-drift", unavailable)).blocker, "native_launch_unavailable");
    const replacement = {projectId: "other-parser-project", projectPath: "/fixture/other-parser", hostId};
    let replacementLaunches = 0;
    const moved = {
        ...desktop,
        async mcp__codex_app__list_projects() {
            return reply({projects: [...fixture.projects.projects, {
                projectKind: "local", projectId: replacement.projectId, path: replacement.projectPath, hostId,
            }]});
        },
        async mcp__codex_app__create_thread() {
            replacementLaunches++;
            return reply({threadId: second, hostId});
        },
    };
    const replacementResult = await dispatch("route-drift", moved, replacement);
    assert.equal(show("route-drift").worker, null, "A resumed reservation must keep its approved project");
    assert.equal(replacementResult.blocker, "native_route_mismatch");
    assert.equal(replacementLaunches, 0);
    const originalRoute = {projectId, projectPath, hostId, environment: {type: "local"}};
    assert.deepEqual(JSON.parse(show("route-drift").launch_route), originalRoute);

    const pending = await dispatch("ready", {...desktop, mcp__codex_app__create_thread: undefined});
    assert.equal(pending.blocker, "native_launch_unavailable");
    assert.equal(show("ready").launch_issued, 0);
    assert.equal(launches.length, 0);
    assert.equal((await dispatch("ready", desktop, {projectId: "wrong"})).blocker, "native_route_mismatch");
    const noProject = {...desktop, async mcp__codex_app__list_projects() { return reply({projects: []}); }};
    assert.equal((await dispatch("ready", noProject)).blocker, "native_project_mismatch");
    assert.equal(launches.length, 0);

    assert.equal((await dispatch("ready")).worker, worker);
    assert.deepEqual([show("ready").worker, show("ready").host, show("ready").state], [worker, hostId, "running"]);
    assert.equal((await dispatch("ready", {exec_command: desktop.exec_command})).worker, worker);
    const revision = ledger("reserve", "parser-revision", "--reuse", "ready", "--objective", objective, "--scope", scope,
        "--requirement", "Include a whitespace case", "--required");
    assert.deepEqual([revision.parent, revision.worker, revision.host, revision.launch], ["ready", worker, hostId, false]);
    assert.equal(launches.length, 1);

    const routeOption = "--launch-route=" + JSON.stringify(originalRoute);
    const routeOptions = ["--objective", objective, "--scope", scope];
    const offline = {exec_command: desktop.exec_command};
    for (const change of [{projectPath: replacement.projectPath}, {hostId: "remote"}, {environment: {type: "worktree"}}]) {
        assert.equal((await dispatch("route-drift", offline, change)).blocker, "native_route_mismatch");
    }
    assert.equal(ledger("reserve", "route-drift", ...routeOptions).launch, false);
    for (const prepare of [[], ["--prepare"]]) {
        const key = prepare.length ? "legacy-pending" : "legacy-claimed";
        ledger("reserve", key, ...routeOptions, ...prepare);
        assert.equal((await dispatch(key, offline)).blocker, "native_route_unavailable");
        assert.equal(show(key).worker, null);
        assert.equal(show(key).launch_issued, prepare.length ? 0 : 1);
    }

    const plan = JSON.stringify([{id: "test", action: "Run check", target: "Parser project", required: true}]);
    ledger("reserve", "preflight", ...routeOptions, routeOption, "--prepare", "--plan", plan);
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
    assert.equal((await dispatch("interrupted", offline, replacement)).blocker, "native_route_mismatch");
    assert.equal(show("interrupted").worker, null);
    candidates = [candidate({id: second, projectId: "wrong"}), candidate({id: coordinator})];
    assert.equal((await dispatch("interrupted")).blocker, "native_launch_unconfirmed");
    changeCompetingDetail = detail => { detail.thread.hostId = "other-host"; };
    candidates = [candidate({})];
    assert.equal((await dispatch("interrupted")).blocker, "native_worker_history_unavailable");
    assert.equal(show("interrupted").worker, null);
    changeCompetingDetail = undefined;
    candidates = [candidate({id: second}), candidate({})];
    assert.equal((await dispatch("interrupted")).blocker, "native_worker_ambiguous");
    assert.equal(show("interrupted").worker, null);

    async function assertPending(shape, tools = desktop) {
        const result = await dispatch("interrupted", tools);
        assert.equal(show("interrupted").worker, null, `A competing assignment with ${shape} must keep recovery unbound`);
        assert.equal(result.blocker, "native_worker_history_unavailable", shape);
        assert.equal(result.launch, false, shape);
        assert.equal(show("interrupted").launch_issued, 1, shape);
        assert.equal(launches.filter(args => args.title.endsWith("interrupted")).length, 1, shape);
    }

    for (const [shape, changeThread] of [
        ["mismatched chat ID", thread => { thread.id = second; }],
        ["omitted chat ID", thread => { delete thread.id; }],
        ["mismatched host", thread => { thread.hostId = "other-host"; }],
        ["omitted host", thread => { delete thread.hostId; }],
        ["mismatched kind", thread => { thread.kind = "chatgpt"; }],
        ["mismatched project", thread => { thread.projectId = "other-project"; }],
        ["mismatched cwd", thread => { thread.cwd = "/fixture/other"; }],
        ["omitted cwd", thread => { delete thread.cwd; }],
        ["mismatched title", thread => { thread.title = "Other worker"; }],
        ["omitted title", thread => { delete thread.title; }],
    ]) {
        changeCompetingDetail = detail => changeThread(detail.thread);
        await assertPending(shape);
    }
    for (const [shape, changeDetail] of [
        ["missing thread metadata", detail => { delete detail.thread; }],
        ["missing turn page metadata", detail => { delete detail.page; }],
        ["omitted turn cursor", detail => { delete detail.page.nextCursor; }],
        ["contradictory turn pagination", detail => { detail.page.hasMore = true; }],
        ["malformed turn cursor", detail => { detail.page.nextCursor = true; detail.page.hasMore = true; }],
        ["incorrect turn order", detail => { detail.page.order = "oldest_first"; }],
        ["empty turn history", detail => { detail.turns = []; }],
        ["missing initial turn ID", detail => { delete detail.turns[0].id; }],
        ["empty item history", detail => { detail.turns[0].items = []; }],
        ["malformed item cursor", detail => { detail.turns[0].nextItemCursor = false; }],
        ["wrong initial item", detail => { detail.turns[0].items[0].name = "other"; }],
    ]) {
        changeCompetingDetail = changeDetail;
        await assertPending(shape);
    }
    for (const [shape, changeOutput] of [
        ["missing text", output => { delete output.text; }],
        ["non-string text", output => { output.text = {value: output.text}; }],
        ["truncated text", output => { output.truncated = true; }],
        ["malformed delegation envelope", output => { output.text = "Unreadable assignment"; }],
    ]) {
        changeCompetingDetail = detail => changeOutput(detail.turns[0].items[0].output);
        await assertPending(shape);
    }
    changeCompetingDetail = undefined;
    for (const [shape, failedReply] of [
        ["a native read error", {isError: true, content: []}],
        ["invalid JSON", {content: [{type: "text", text: "{"}]}],
    ]) {
        await assertPending(shape, {
            ...desktop,
            async mcp__codex_app__read_thread(args) {
                if (args.threadId === worker) return failedReply;
                return desktop.mcp__codex_app__read_thread(args);
            },
        });
    }
    pageCompetingHistory = true;
    changeCompetingDetail = (detail, cursor) => {
        if (cursor) detail.thread.id = second;
    };
    await assertPending("mismatched chat on an older turn page");
    changeCompetingDetail = (detail, cursor) => {
        if (cursor) detail.page = {...detail.page, hasMore: true, nextCursor: cursor};
    };
    await assertPending("repeated turn cursor");
    changeCompetingDetail = undefined;
    for (const [shape, changeItems] of [
        ["mismatched chat on an item page", page => { page.threadId = second; }],
        ["omitted chat on an item page", page => { delete page.threadId; }],
        ["mismatched turn on an item page", page => { page.turnId = second; }],
        ["omitted turn on an item page", page => { delete page.turnId; }],
        ["omitted item page cursor", page => { delete page.nextItemCursor; }],
        ["repeated item cursor", page => { page.nextItemCursor = "older-items"; }],
        ["empty item page", page => { page.items = []; }],
    ]) {
        changeCompetingItems = changeItems;
        await assertPending(shape);
    }
    changeCompetingItems = undefined;
    assert.equal((await dispatch("interrupted")).worker, second,
        "An exact match and a validated different assignment permit unique recovery");
    pageCompetingHistory = false;
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

    const environment = {type: "worktree", startingState: {type: "branch", branchName: "approved"}};
    assert.equal((await dispatch("worktree", unavailable, {environment})).blocker, "native_launch_unavailable");
    const changedBranch = {type: "worktree", startingState: {type: "branch", branchName: "other"}};
    assert.equal((await dispatch("worktree", offline, {environment: changedBranch})).blocker, "native_route_mismatch");
    let worktreeLaunches = 0;
    const worktreeDesktop = {...desktop, async mcp__codex_app__create_thread({target}) {
        assert.deepEqual(target, {type: "project", projectId, environment});
        worktreeLaunches++;
        return reply({threadId: "66666666-6666-4666-8666-666666666666", hostId});
    }};
    const confirmed = {startingState: {branchName: "approved", type: "branch"}, type: "worktree"};
    assert.equal((await dispatch("worktree", worktreeDesktop, {environment: confirmed})).state, "running");
    assert.equal(worktreeLaunches, 1);

    const lostWorktreeReply = {...desktop, async mcp__codex_app__create_thread(args) {
        assert.deepEqual(args.target, {type: "project", projectId, environment});
        launches.push(args);
        throw Error("Fixture lost its native worktree launch reply");
    }};
    const worktreeRoute = {environment};
    const worktreeKey = "worktree-interrupted";
    assert.equal((await dispatch(worktreeKey, lostWorktreeReply, worktreeRoute)).blocker,
        "native_launch_failed_or_unconfirmed");
    competingWorker = "77777777-7777-4777-8777-777777777777";
    candidates = [candidate({id: competingWorker, cwd: "/fixture/worktree"})];
    changeCompetingDetail = detail => { detail.thread.cwd = projectPath; };
    assert.equal((await dispatch(worktreeKey, lostWorktreeReply, worktreeRoute)).blocker,
        "native_worker_history_unavailable");
    assert.equal(show(worktreeKey).worker, null);
    changeCompetingDetail = undefined;
    assert.equal((await dispatch(worktreeKey, lostWorktreeReply, worktreeRoute)).worker, competingWorker);
    assert.equal(launches.filter(args => args.title.endsWith(worktreeKey)).length, 1);
}

const root = mkdtempSync(join(tmpdir(), "codexos-dispatch-worker-"));
run(root).catch(error => {
    console.error(error);
    process.exitCode = 1;
}).finally(() => rmSync(root, {recursive: true}));
