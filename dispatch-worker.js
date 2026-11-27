// Evaluate in desktop code mode and call with the coordinator's bot directory.
(async function dispatchWorker(tools, workdir, {
    key, objective, scope, brief, projectId, projectPath, hostId, environment = {type: "local"},
}) {
    const validChat = value => typeof value === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value);
    const nonempty = value => typeof value === "string" && value.trim() && !value.includes("\0");
    if (typeof key !== "string" || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(key) ||
        ![objective, scope, brief, projectId, projectPath, hostId].every(nonempty) ||
        !["local", "worktree"].includes(environment?.type))
        throw Error("Supply the dispatch objective, scope, brief and approved Codex project, host and environment");

    const launchRoute = JSON.stringify({projectId, projectPath, hostId, environment});
    const title = "CodexOS worker " + key;
    const prompt = [
        "CodexOS dispatch " + key + ". You are the temporary worker for this assignment.",
        "Objective: " + objective,
        "Approved scope: " + scope,
        brief,
    ].join("\n\n");
    // Native history can return up to 20,000 characters per item, including the envelope.
    if (prompt.length > 18000) throw Error("Shorten the worker brief and reference approved local evidence");

    const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
    async function shell(cmd) {
        let result = await tools.exec_command({cmd, workdir});
        let output = result.output;
        while (result.session_id && result.exit_code == null) {
            result = await tools.write_stdin({session_id: result.session_id, chars: ""});
            output += result.output;
        }
        if (result.exit_code !== 0) throw Error(output.trim() || "Dispatch command failed");
        return JSON.parse(output);
    }
    const cli = (...args) => shell("python3 ../../codexos.py dispatch " + args.map(quote).join(" "));
    async function native(name, args) {
        const reply = await tools["mcp__codex_app__" + name](args);
        if (reply.isError) throw Error("Native Codex operation failed");
        const payloads = reply.content.filter(item => item.type === "text");
        if (payloads.length !== 1 || typeof payloads[0].text !== "string") throw Error("Invalid native response envelope");
        return JSON.parse(payloads[0].text);
    }

    const context = "import json, os; print(json.dumps([json.load(open('bot.json'))['primary_thread'], os.getenv('CODEX_THREAD_ID')]))";
    const [primary, current] = await shell("python3 -c " + quote(context));
    if (!validChat(primary) || current !== primary)
        throw Error("Run worker dispatch in the registered coordinator chat");
    const request = ["reserve", key, "--objective=" + objective, "--scope=" + scope, "--launch-route=" + launchRoute];
    const prepared = await cli(...request, "--prepare");
    if (prepared.worker || prepared.state !== "reserved" || prepared.blocker) return prepared;
    if ((prepared.permissions?.status ?? "ready") !== "ready") return {...prepared, blocker: "permission_preflight"};

    function pending(record, blocker, details = {}) {
        return {...record, ...details, launch: false, blocker};
    }

    const {environment: approvedEnvironment} = JSON.parse(prepared.launch_route);
    let projects;
    try {
        ({projects} = await native("list_projects", {}));
        projects = projects.filter(project => project.path === projectPath && project.hostId === hostId &&
            ["local", "remote"].includes(project.projectKind));
    } catch {
        return pending(prepared, "native_project_list_unavailable");
    }
    if (projects.length !== 1 || projects[0].projectId !== projectId ||
        (approvedEnvironment.type === "worktree" && projects[0].isGitRepository !== true))
        return pending(prepared, "native_project_mismatch");

    const envelope = "<codex_delegation>\n  <source_thread_id>" + primary +
        "</source_thread_id>\n  <input>" + prompt + "</input>\n</codex_delegation>";

    // Keep the recovery checks in sync with the other standalone desktop adapter.
    function validateCursor(cursor, seen) {
        if (cursor === null) return;
        if (!nonempty(cursor) || seen.has(cursor)) throw Error("Invalid worker history cursor");
        seen.add(cursor);
    }

    function validateHistoryPage(history, cursors, chatIds) {
        validateCursor(history.nextCursor, cursors);
        if (!Array.isArray(history.threads) || history.threads.length > 50) throw Error("Invalid worker history page");
        for (const chat of history.threads) {
            if (!validChat(chat?.id) || !nonempty(chat.kind) || !nonempty(chat.hostId) ||
                !nonempty(chat.title) || !nonempty(chat.cwd) ||
                (chat.projectId !== null && !nonempty(chat.projectId)) ||
                (chat.clientThreadId != null && !nonempty(chat.clientThreadId)) || chatIds.has(chat.id))
                throw Error("Invalid or repeated worker history entry");
            chatIds.add(chat.id);
        }
    }

    async function readAssignment(read, candidate, projectId, maxOutputCharsPerItem) {
        const {id, hostId, title, cwd} = candidate;
        const args = {threadId: id, hostId, includeOutputs: true, maxOutputCharsPerItem};
        const cursors = new Set();
        const turnsSeen = new Set();
        let cursor, turn, projectKnown = candidate.projectId === projectId;
        for (let page = 0; page < 5; page++) {
            const {thread, page: pagination, turns} = await read({...args, cursor, turnLimit: 10, itemLimit: 100});
            if (thread?.id !== id || thread.kind !== "codex" || thread.hostId !== hostId ||
                thread.title !== title || thread.cwd !== cwd ||
                (thread.projectId != null && thread.projectId !== projectId))
                throw Error("Worker detail differs from native history");
            projectKnown ||= thread.projectId === projectId;
            if (!Array.isArray(turns) || !turns.length || turns.length > 10 || pagination?.order !== "newest_first" ||
                pagination.hasMore !== (pagination.nextCursor !== null))
                throw Error("Worker turn history incomplete");
            for (const row of turns) {
                if (!nonempty(row?.id) || turnsSeen.has(row.id)) throw Error("Invalid or repeated worker turn");
                turnsSeen.add(row.id);
            }
            turn = turns.at(-1);
            cursor = pagination.nextCursor;
            validateCursor(cursor, cursors);
            if (cursor === null) break;
        }
        if (cursor !== null) throw Error("Initial worker turn unavailable");

        // Native turn summaries may omit a terminal item cursor. Continuations carry it explicitly.
        let {items, nextItemCursor = null} = turn;
        cursors.clear();
        const itemsSeen = new Set();
        for (let page = 0; page <= 5; page++) {
            if (!Array.isArray(items) || !items.length || items.length > 100) throw Error("Initial worker item unavailable");
            for (const item of items) {
                if (!nonempty(item?.type) || !nonempty(item.id) || itemsSeen.has(item.id))
                    throw Error("Invalid or repeated worker item");
                itemsSeen.add(item.id);
            }
            validateCursor(nextItemCursor, cursors);
            if (nextItemCursor === null) {
                const [input] = items;
                if (input.type !== "functionCallOutput" || input.namespace !== "codex_app" ||
                    input.name !== "create_thread" || input.output?.truncated !== false ||
                    typeof input.output.text !== "string")
                    throw Error("Initial worker assignment unavailable");
                const assignment = /^<codex_delegation>\n  <source_thread_id>([^\n]+)<\/source_thread_id>\n  <input>([\s\S]+)<\/input>\n<\/codex_delegation>$/.exec(input.output.text);
                if (!assignment || assignment[0] !== input.output.text || !validChat(assignment[1]) || !nonempty(assignment[2]))
                    throw Error("Initial worker assignment invalid");
                return {envelope: input.output.text, projectKnown};
            }
            if (page === 5) break;
            const next = await read({...args, itemCursor: nextItemCursor, itemLimit: 100});
            if (next.threadId !== id || next.turnId !== turn.id)
                throw Error("Worker item page differs from its chat or turn");
            ({items, nextItemCursor} = next);
        }
        throw Error("Initial worker item unavailable");
    }

    async function recover(record) {
        const candidates = [];
        const chatIds = new Set();
        let matches;
        try {
            for (const archived of [false, true]) {
                let cursor;
                const cursors = new Set();
                for (let page = 0; page < 5; page++) {
                    const history = await native("list_threads", {mode: "history", hostId, archived, cursor, limit: 50});
                    validateHistoryPage(history, cursors, chatIds);
                    for (const chat of history.threads) {
                        if (chat.kind === "codex" && chat.id !== primary && chat.hostId === hostId && chat.title === title &&
                            (chat.projectId === null || chat.projectId === projectId) &&
                            (approvedEnvironment.type === "worktree" || chat.cwd === projectPath))
                            candidates.push(chat);
                    }
                    cursor = history.nextCursor;
                    if (cursor === null) break;
                }
                if (cursor !== null) throw Error("Worker history search incomplete");
            }
            matches = [];
            const read = args => native("read_thread", args);
            for (const chat of candidates) {
                const assignment = await readAssignment(read, chat, projectId, 20000);
                if (assignment.envelope !== envelope) continue;
                if (!assignment.projectKnown) throw Error("Worker project unavailable");
                matches.push(chat.id);
            }
        } catch {
            return pending(record, "native_worker_history_unavailable");
        }
        if (matches.length === 1) return cli("bind", key, matches[0], "--host=" + hostId);
        return pending(record, matches.length ? "native_worker_ambiguous" : "native_launch_unconfirmed");
    }

    if (prepared.launch_issued) return recover(prepared);
    if (typeof tools.mcp__codex_app__create_thread !== "function")
        return pending(prepared, "native_launch_unavailable");
    const claimed = await cli(...request);
    if (!claimed.launch) {
        if (claimed.worker || claimed.state !== "reserved" || claimed.blocker) return claimed;
        if ((claimed.permissions?.status ?? "ready") !== "ready") return pending(claimed, "permission_preflight");
        return recover(claimed);
    }

    let worker;
    try {
        worker = await native("create_thread", {title, prompt, target: {type: "project", projectId, environment: approvedEnvironment}});
    } catch {
        // A failure can arrive after creation. Preserve the claim for read-only recovery.
        return pending(claimed, "native_launch_failed_or_unconfirmed");
    }
    if (worker?.hostId === hostId && validChat(worker.threadId) && worker.threadId !== primary &&
        worker.clientThreadId == null &&
        (worker.projectId == null || worker.projectId === projectId))
        return cli("bind", key, worker.threadId, "--host=" + hostId);
    if (!worker?.threadId && nonempty(worker?.clientThreadId) &&
        (worker.hostId == null || worker.hostId === hostId) &&
        (worker.projectId == null || worker.projectId === projectId))
        return pending(claimed, "native_worker_setup_pending", {clientThreadId: worker.clientThreadId});
    return pending(claimed, "native_launch_reply_mismatch");
})
