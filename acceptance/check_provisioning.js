// Run the checked-in desktop adapter with real CLI commands and controlled native Codex replies.
const assert = require("node:assert/strict");
const {execFileSync} = require("node:child_process");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const provisionBot = eval(readFileSync(join(__dirname, "../provision-bot.js"), "utf8"));
const [, , fleet, python] = process.argv;
const chief = join(fleet, "bots/chief-of-staff");
const cli = (...args) => JSON.parse(execFileSync(python, [join(fleet, "codexos.py"), ...args], {
    cwd: chief, encoding: "utf8",
}));
const reply = data => ({content: [{type: "text", text: JSON.stringify(data)}]});
const hostId = "local";
const projectId = "project";
const chatId = "11111111-1111-4111-8111-111111111111";

function scenario(id) {
    cli("create-bot", id, "--name", "Trial specialist", "--mission", "Exercise startup");
    const directory = join(fleet, "bots", id);
    const project = {projectId, hostId, projectKind: "local", path: directory};
    const chat = {id: chatId, hostId, projectId, kind: "codex", cwd: directory, title: "CodexOS Main - " + id};
    const plan = {
        projects: [project], chats: [], archived: [], launchCount: 0, loseLaunchReply: false,
        itemDirectory: directory, chatDirectory: directory, exitCode: 0, turnStatus: "inProgress",
        answer: "CodexOS ready: " + id, phase: "final_answer",
    };
    const tools = {
        async exec_command({cmd, workdir}) {
            assert.equal(workdir, chief);
            const [interpreter, script, ...args] = cmd.split(" ");
            assert.equal(interpreter, "python3");
            assert.equal(script, "../../codexos.py");
            return {exit_code: 0, output: JSON.stringify(cli(...args))};
        },
        async mcp__codex_app__list_projects() {
            return reply({projects: plan.projects});
        },
        async mcp__codex_app__list_threads({mode, hostId: requestedHost, archived, cursor}) {
            assert.equal(mode, "history");
            assert.equal(requestedHost, hostId);
            if (archived) return reply({threads: plan.archived});
            // Ensure recovery checks more than the first page.
            return cursor ? reply({threads: plan.chats}) : reply({threads: [], nextCursor: "page-two"});
        },
        async mcp__codex_app__create_thread({target, title, prompt}) {
            assert.deepEqual(target, {type: "project", projectId, environment: {type: "local"}});
            assert.equal(title, chat.title);
            plan.launchCount++;
            plan.prompt = prompt;
            if (plan.deferLaunch) return reply({clientThreadId: chatId});
            plan.chats.push(chat);
            if (plan.loseLaunchReply) throw Error("Lost launch acknowledgement");
            return reply({threadId: chatId, hostId});
        },
        async mcp__codex_app__read_thread({threadId, hostId: requestedHost}) {
            assert.equal(threadId, chatId);
            assert.equal(requestedHost, hostId);
            return reply({
                thread: {...chat, cwd: plan.chatDirectory, status: {type: plan.turnStatus === "inProgress" ? "active" : "idle"}},
                turns: [{status: plan.turnStatus, items: [
                    {type: "userMessage", content: [{type: "text", text: plan.prompt}]},
                    {type: "commandExecution", command: "/bin/zsh -lc 'python3 ../../codexos.py status'",
                        cwd: plan.itemDirectory, status: "completed", exitCode: plan.exitCode},
                    {type: "agentMessage", phase: plan.phase, text: plan.answer},
                ]}],
            });
        },
    };
    const manifest = () => JSON.parse(readFileSync(join(directory, "bot.json"), "utf8"));
    const proposed = () => {
        assert.equal(manifest().lifecycle, "proposed");
        assert.equal(manifest().primary_thread, null);
    };
    const active = () => {
        assert.equal(manifest().lifecycle, "active");
        assert.equal(manifest().primary_thread, chatId);
    };
    return {plan, project, chat, proposed, active, run: () => provisionBot(tools, chief, id)};
}

async function check() {
    const trial = scenario("delivery-tracker");
    trial.plan.projects = [
        {...trial.project, path: trial.project.path + "-other"},
        {...trial.project, projectKind: "remote", hostId: "remote"},
    ];
    const waiting = await trial.run();
    assert.equal(waiting.status, "waiting_for_registration");
    assert.equal(waiting.directory, trial.project.path);
    assert.match(waiting.action, /project picker/);
    trial.proposed();
    assert.equal(trial.plan.launchCount, 0);

    trial.plan.projects = [trial.project];
    const concurrent = await Promise.all([trial.run(), trial.run()]);
    assert.ok(concurrent.some(result => result.status === "waiting_for_startup"));
    assert.equal((await trial.run()).status, "waiting_for_startup");
    trial.proposed();
    assert.equal(trial.plan.launchCount, 1);

    trial.plan.turnStatus = "failed";
    assert.equal((await trial.run()).status, "verification_required");
    trial.proposed();
    trial.plan.turnStatus = "completed";
    trial.plan.chatDirectory += "-wrong";
    assert.equal((await trial.run()).status, "main_chat_mismatch");
    trial.plan.chatDirectory = trial.project.path;

    trial.plan.exitCode = 1;
    assert.equal((await trial.run()).status, "verification_required");
    trial.plan.exitCode = 0;
    trial.plan.phase = "commentary";
    assert.equal((await trial.run()).status, "verification_required");
    trial.plan.phase = "final_answer";
    trial.plan.answer = "Startup files are unavailable";
    const failed = await trial.run();
    assert.equal(failed.status, "verification_required");
    assert.equal(failed.chatId, chatId);
    assert.equal(failed.prompt, trial.plan.prompt);
    trial.proposed();

    trial.plan.answer = "CodexOS ready: delivery-tracker";
    trial.plan.itemDirectory = chief;
    assert.equal((await trial.run()).status, "verification_required");
    trial.proposed();
    assert.equal(trial.plan.launchCount, 1);

    trial.plan.itemDirectory = trial.project.path;
    const startup = JSON.parse(execFileSync(python, [join(fleet, "codexos.py"), "status"], {
        cwd: trial.project.path, encoding: "utf8",
    }));
    assert.equal(startup.bot, "delivery-tracker");
    assert.equal(startup.integrity, "ok");
    assert.equal((await trial.run()).status, "active");
    trial.active();
    trial.plan.answer = "A later conversation reply";
    assert.equal((await trial.run()).status, "active");
    assert.equal(trial.plan.launchCount, 1);

    const lost = scenario("lost-acknowledgement");
    lost.plan.loseLaunchReply = true;
    assert.equal((await lost.run()).status, "launch_unconfirmed");
    lost.proposed();
    lost.plan.turnStatus = "completed";
    assert.equal((await lost.run()).status, "active");
    lost.active();
    assert.equal(lost.plan.launchCount, 1);

    const deferred = scenario("deferred");
    deferred.plan.deferLaunch = true;
    assert.equal((await deferred.run()).status, "waiting_for_startup");
    assert.equal((await deferred.run()).status, "waiting_for_main_chat");
    deferred.proposed();
    deferred.plan.chats.push(deferred.chat);
    deferred.plan.turnStatus = "completed";
    assert.equal((await deferred.run()).status, "active");
    deferred.active();
    assert.equal(deferred.plan.launchCount, 1);

    const existing = scenario("existing-proposal");
    existing.plan.chats.push({...existing.chat, title: "Trial specialist"});
    existing.plan.turnStatus = "completed";
    const review = await existing.run();
    assert.equal(review.status, "verification_required");
    existing.proposed();
    existing.plan.prompt = review.prompt;
    assert.equal((await existing.run()).status, "active");
    existing.active();
    assert.equal(existing.plan.launchCount, 0);

    const archived = scenario("archived-main");
    archived.plan.archived.push(archived.chat);
    assert.equal((await archived.run()).status, "main_chat_archived");
    archived.proposed();
    assert.equal(archived.plan.launchCount, 0);
}

check().catch(error => { console.error(error); process.exitCode = 1; });
