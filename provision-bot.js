// Run in the desktop code-mode tool runtime with the Chief of Staff project as workdir.
(async function provisionBot(tools, workdir, id, {approveManifestWrite = false} = {}) {
    if (typeof id !== "string" || !/^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/.test(id) || id.length > 64)
        throw Error("Select a valid specialist bot ID");

    async function cli(flag, chatId, readSchedule = false) {
        if (chatId !== undefined && !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(chatId))
            throw Error("Invalid native chat ID");
        const cmd = readSchedule ? "python3 ../../codexos.py --bot " + id + " schedule status" :
            ["python3 ../../codexos.py provision-bot", id, flag, chatId].filter(Boolean).join(" ");
        const approval = flag === "--activate" && approveManifestWrite ? {
            sandbox_permissions: "require_escalated",
            justification: "May I save the verified main chat and active status in this specialist's local bot manifest?",
        } : {};
        let result = await tools.exec_command({cmd, workdir, ...approval});
        let output = result.output;
        while (result.session_id && result.exit_code == null) {
            result = await tools.write_stdin({session_id: result.session_id, chars: ""});
            output += result.output;
        }
        if (result.exit_code !== 0) throw Error(output.trim() || "Fleet command failed");
        return JSON.parse(output);
    }
    async function native(operation, args) {
        const reply = await tools[operation](args);
        if (reply.isError) throw Error("Native Codex operation failed: " + operation);
        return JSON.parse(reply.content.find(item => item.type === "text").text);
    }

    let state = await cli();
    const directory = state.project;
    const status = (status, action, details = {}) => ({
        status, botId: id, lifecycle: state.lifecycle, directory, ...(action ? {action} : {}), ...details,
    });
    let projects;
    try {
        projects = (await native("mcp__codex_app__list_projects", {})).projects.filter(project =>
            project.projectKind === "local" && project.hostId === "local" && project.path === directory);
    } catch {
        return status("project_verification_pending", "Restore access to the Codex project list, then resume.");
    }
    if (projects.length === 0)
        return status("waiting_for_registration", "Add this exact folder in the Codex project picker, then resume with the same bot ID.");
    if (projects.length !== 1)
        return status("ambiguous_project", "Resolve duplicate Codex project registrations for this folder, then resume.");

    const {projectId, hostId} = projects[0];
    const title = "CodexOS Main - " + id;
    const command = "python3 ../../codexos.py status";
    const previousMarker = "CodexOS ready: " + id;
    const startupMarker = state.onboarding ? "CodexOS startup verified: " + id : previousMarker;
    const startupPrompt = marker => [
        "This is the dedicated main chat startup check for CodexOS bot " + id + ".",
        "From the current project directory, read bot.json, SOUL.md, USER.md, and MEMORY.md.",
        "Run `" + command + "` as a standalone command from that directory.",
        "If all four files are readable, the status bot is " + id + ", and integrity is ok, reply exactly: " + marker,
        "Otherwise report the blocker. Do not change the manifest, configure sources or schedules, or delegate this check.",
    ].join("\n");
    const prompt = startupPrompt(startupMarker);
    function matchesStartupInput(item, expected) {
        if (item?.type === "userMessage") {
            return item.content?.length === 1 && item.content[0]?.type === "text" && item.content[0].text === expected;
        }
        if (item?.type !== "functionCallOutput" || item.namespace !== "codex_app" || item.name !== "create_thread")
            return false;
        const output = item.output;
        if (output?.truncated !== false || typeof output.text !== "string") return false;
        const header = output.text.match(/^<codex_delegation>\n  <source_thread_id>[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}<\/source_thread_id>\n  <input>/);
        return header !== null && output.text === header[0] + expected + "</input>\n</codex_delegation>";
    }
    async function matches(archived) {
        const found = [];
        let cursor;
        do {
            const page = await native("mcp__codex_app__list_threads", {mode: "history", hostId, archived, cursor, limit: 50});
            found.push(...page.threads.filter(chat => chat.kind === "codex" && chat.hostId === hostId &&
                chat.projectId === projectId && chat.cwd === directory &&
                (state.candidate ? chat.id === state.candidate : chat.title === title || chat.title === state.name)));
            cursor = page.nextCursor;
        } while (cursor);
        return found;
    }

    async function readiness(chatId) {
        const plan = state.onboarding;
        const main = {chatId, startupVerified: true, setupReady: false};
        if (!plan) return status("active", null, {...main, setupReady: null});
        if (plan.issue) return status("routine_setup_pending", plan.issue, main);

        // Onboarding receipts name native turns. Read only a bounded part of the bound chat.
        let history;
        async function findTurn(turnId) {
            if (!history) {
                history = [];
                let cursor;
                for (let page = 0; page < 5; page++) {
                    const result = await native("mcp__codex_app__read_thread", {
                        threadId: chatId, hostId, cursor, turnLimit: 10, itemLimit: 100, includeOutputs: true,
                    });
                    if (result.thread?.id !== chatId || result.thread.kind !== "codex" ||
                        result.thread.hostId !== hostId || result.thread.cwd !== directory)
                        throw Error("Native history is from a different chat");
                    history.push(...result.turns);
                    cursor = result.page?.nextCursor;
                    if (!cursor) break;
                }
            }
            return history.find(turn => turn.id === turnId && turn.status === "completed");
        }
        function successfulRun(turn, routinePrompt, marker, scheduled) {
            if (!turn || turn.nextItemCursor) return false;
            const items = turn.items ?? [];
            const input = items[0];
            const match = scheduled
                ? input?.type === "functionCallOutput" && input.namespace === "codex_app" &&
                  input.name === "automation_update" && input.output?.truncated === false &&
                  input.output.text?.startsWith("<heartbeat>") && input.output.text.includes(routinePrompt)
                : input?.type === "userMessage" && input.content?.length === 1 &&
                  input.content[0]?.type === "text" && input.content[0].text === routinePrompt;
            const answer = items.findLast(item => item.type === "agentMessage" && item.phase === "final_answer");
            return match && (scheduled || answer?.text?.trimEnd().split("\n").at(-1) === marker);
        }
        const reference = value => typeof value === "string" && value.trim().length > 0;

        for (const routine of plan.routines) {
            const {id: routineId, file, revision, review, schedule} = routine;
            const marker = "CodexOS routine verified: " + id + "/" + routineId + " " + revision;
            const prompt = [
                "CodexOS manual baseline for " + id + "/" + routineId + " (" + revision + ").",
                "From this bot project, read AGENTS.md and execute " + file + " once within existing authorization.",
                "Report the result for onboarding review, including evidence of what ran.",
                "If the routine succeeds, end with this exact line: " + marker,
                "If any step is blocked, report the blocker and omit the success line.",
            ].join("\n");
            const details = {...main, routineId, revision, evidenceFile: plan.evidence_file};
            try {
                if (!reference(review.manual_review) || !reference(review.manual_turn) ||
                    !successfulRun(await findTurn(review.manual_turn), prompt, marker, false))
                    return status("manual_baseline_pending",
                        "Review and record the baseline in the verified main chat. Run the prompt once if the baseline is missing.",
                        {...details, prompt});
                if (!schedule) continue;

                const scheduledPrompt = [
                    "CodexOS scheduled run for " + id + "/" + routineId + " (" + revision + ").",
                    "From this bot project, read AGENTS.md and execute " + file + " once within existing authorization.",
                    "Report any actionable finding with evidence. End quietly when the routine returns no finding.",
                ].join("\n");
                const saved = review.schedule;
                if (!reference(saved?.approval))
                    return status("schedule_approval_pending", "Record the operator's separate schedule authorization, then resume.",
                        {...details, schedule, scheduledPrompt});
                if (!reference(saved?.id) || !reference(saved.review) || saved.status !== "ACTIVE" ||
                    saved.target_chat !== chatId || saved.prompt !== scheduledPrompt ||
                    ["cadence", "window", "timezone"].some(key => schedule[key] !== saved[key]))
                    return status("schedule_verification_pending",
                        "Verify the authorized automation in Codex and record its settings. Create it only if Codex confirms it is missing.",
                        {...details, schedule, scheduledPrompt});
                if (!reference(saved.first_turn) || !reference(saved.first_review) ||
                    !successfulRun(await findTurn(saved.first_turn), scheduledPrompt, marker, true))
                    return status("first_run_pending", "Review and record the first successful native run of this automation, then resume.",
                        {...details, automationId: saved.id});
            } catch {
                return status("routine_history_pending", "Restore access to the native routine history, then resume.", details);
            }
        }
        if (plan.dispatcher) {
            const {minutes, window, timezone, revision, review} = plan.dispatcher;
            const schedule = {minutes, window, timezone};
            const marker = "CodexOS heartbeat verified: " + id + " " + revision;
            const scheduledPrompt = [
                "CodexOS delegated heartbeat for " + id + " (" + revision + ").",
                "Run the checked-in ../../heartbeat.js once in desktop code mode with tools, the bot's absolute project path, and {automationId: ID} from this native wakeup's automation_id.",
                "The dispatcher handles due work. Report any actionable dispatch problem and otherwise end quietly.",
                "If the dispatcher returns first_tick: true, record this exact line: " + marker,
            ].join("\n");
            const details = {...main, revision, schedule, scheduledPrompt, projectId, evidenceFile: plan.evidence_file};
            const saved = review.schedule;
            if (review.revision !== revision || !reference(saved?.approval))
                return status("schedule_approval_pending", "Record the separate authorization for this bot’s one heartbeat.", details);
            if (!reference(saved.id) || !reference(saved.review) || saved.status !== "ACTIVE" ||
                saved.target_chat !== chatId || saved.prompt !== scheduledPrompt ||
                saved.minutes !== minutes || saved.timezone !== timezone ||
                saved.window?.start !== window.start || saved.window?.end !== window.end ||
                JSON.stringify(saved.window?.days) !== JSON.stringify(window.days))
                return status("schedule_verification_pending", "Verify the single authorized native heartbeat and record its settings.", details);
            const binding = await cli(undefined, undefined, true).catch(() => ({}));
            if (binding.automation !== saved.id || binding.plan !== revision || binding.chat !== chatId ||
                binding.project !== projectId)
                return status("schedule_binding_pending", "Record the verified heartbeat with the fleet CLI.", {...details, automationId: saved.id});
            try {
                const turn = reference(saved.first_turn) && await findTurn(saved.first_turn);
                const input = turn?.items?.[0]?.output?.text;
                const envelope = input?.match(/^<heartbeat>\n  <automation_id>([^<]+)<\/automation_id>\n  <current_time_iso>[^<]+<\/current_time_iso>\n  <instructions>\n([\s\S]*)\n  <\/instructions>\n<\/heartbeat>\n?$/);
                const answer = turn?.items?.findLast(item => item.type === "agentMessage" && item.phase === "final_answer");
                const witnessedTick = [binding.first_usable_tick, binding.first_tick].some(tick =>
                    Number.isFinite(tick) && Math.floor(tick) >= turn?.startedAt && Math.floor(tick) <= turn?.completedAt);
                if (!witnessedTick || !reference(saved.first_review) ||
                    !successfulRun(turn, scheduledPrompt, marker, true) ||
                    envelope?.[1] !== saved.id || envelope?.[2] !== scheduledPrompt ||
                    !Number.isFinite(turn.startedAt) || !Number.isFinite(turn.completedAt) ||
                    answer?.text?.trimEnd().split("\n").at(-1) !== marker)
                    return status("first_run_pending", "Verify the first native run and its ledger tick, then record the turn.", details);
            } catch {
                return status("routine_history_pending", "Restore access to the native heartbeat history, then resume.", details);
            }
        }
        return status("ready", null, {...main, setupReady: true});
    }

    let chats;
    try {
        chats = await matches(false);
    } catch {
        return status("main_chat_verification_pending", "Restore access to native chat history, then resume.");
    }
    if (chats.length > 1)
        return status("ambiguous_main_chat", "Resolve the matching main chats in this project, then resume.");
    if (chats.length === 0) {
        try {
            if ((await matches(true)).length)
                return status("main_chat_archived", "Unarchive the existing main chat in this project, then resume.");
        } catch {
            return status("main_chat_verification_pending", "Restore access to archived chat history, then resume.");
        }
        if (state.candidate)
            return status("waiting_for_main_chat", "Check that the recorded chat is visible in this project, then resume.",
                {chatId: state.candidate});
        state = await cli("--reserve");
        if (!state.launch)
            return status("waiting_for_main_chat",
                "Check Codex for the existing launch. If Codex confirms that launch failed, manually start one chat in this project with the title and prompt below, then resume.",
                {title, prompt});

        let created;
        try {
            created = await native("mcp__codex_app__create_thread", {
                title, prompt, target: {type: "project", projectId, environment: {type: "local"}},
            });
        } catch (error) {
            return status("launch_unconfirmed", "Check whether Codex started the chat, then resume.",
                {title, prompt, error: String(error.message || error)});
        }
        if (created.threadId && created.hostId === hostId) {
            await cli("--remember", created.threadId);
        } else if (!created.clientThreadId) {
            return status("launch_unconfirmed", "Check the chat's project and host before resuming.", {title, prompt});
        }
        return status("waiting_for_startup", "Resume once Codex finishes the main chat startup check.");
    }

    const chatId = chats[0].id;
    let detail;
    try {
        detail = await native("mcp__codex_app__read_thread", {threadId: chatId, hostId, itemLimit: 100, includeOutputs: true});
    } catch {
        return status("main_chat_verification_pending", "Restore access to the main chat's native history, then resume.", {chatId});
    }
    if (detail.thread?.id !== chatId || detail.thread.kind !== "codex" ||
        detail.thread.hostId !== hostId || detail.thread.cwd !== directory)
        return status("main_chat_mismatch", "Check the main chat's project and working directory before resuming.", {chatId});
    if (state.lifecycle === "active" && state.verified) return readiness(chatId);

    const turn = detail.turns?.[0];
    if (detail.thread.status?.type === "active" || turn?.status === "inProgress")
        return status("waiting_for_startup", "Resume when the main chat's startup turn finishes.", {chatId});

    const items = turn?.items ?? [];
    const ranStatus = items.some(item => item.type === "commandExecution" && item.cwd === directory &&
        [command, "'" + command + "'", '"' + command + '"'].includes(
            item.command?.replace(/^(?:\S+\/)?(?:sh|bash|zsh) -lc /, "")) &&
        item.status === "completed" && item.exitCode === 0);
    const answer = items.findLast(item => item.type === "agentMessage" && item.phase === "final_answer");
    const requested = !turn?.nextItemCursor && [startupMarker, previousMarker].some(marker =>
        answer?.text?.trim() === marker && matchesStartupInput(items[0], startupPrompt(marker)));
    if (turn?.status !== "completed" || !requested || !ranStatus)
        return status("verification_required", "Resolve the startup blocker, then submit this startup prompt in the same chat and resume.",
            {chatId, prompt});

    if (!state.candidate) await cli("--remember", chatId);
    try {
        state = await cli("--activate", chatId);
    } catch (error) {
        return status("main_chat_activation_pending", "Resolve the manifest write blocker, then resume.",
            {chatId, startupVerified: true, error: error.message});
    }
    if (state.lifecycle !== "active" || state.primary_thread !== chatId || !state.verified)
        throw Error("The fleet CLI did not confirm activation");
    return readiness(chatId);
})
