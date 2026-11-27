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
        return JSON.parse(reply.content.find(item => item.type === "text").text);
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

    const matchesChat = chat => chat.kind === "codex" && chat.id !== primary && validChat(chat.id) &&
        chat.hostId === hostId && (approvedEnvironment.type === "worktree" || chat.cwd === projectPath);
    const envelope = "<codex_delegation>\n  <source_thread_id>" + primary +
        "</source_thread_id>\n  <input>" + prompt + "</input>\n</codex_delegation>";

    function validateCursor(cursor, seen) {
        if (cursor === null) return;
        if (typeof cursor !== "string" || !cursor || seen.has(cursor))
            throw Error("Invalid worker detail cursor");
        seen.add(cursor);
    }

    async function hasAssignment(candidate) {
        const {id} = candidate;
        const args = {threadId: id, hostId, includeOutputs: true, maxOutputCharsPerItem: 20000};
        const seen = new Set();
        let cursor, turn;
        for (let page = 0; page < 5; page++) {
            const detail = await native("read_thread", {...args, cursor, turnLimit: 10, itemLimit: 100});
            const {thread, page: pagination, turns} = detail;
            if (thread?.id !== id || !matchesChat(thread) || thread.title !== candidate.title ||
                (thread.projectId != null && thread.projectId !== projectId) ||
                (approvedEnvironment.type === "worktree" && (!nonempty(thread.cwd) ||
                    (candidate.cwd != null && thread.cwd !== candidate.cwd))))
                throw Error("Worker detail differs from native history");
            if (!Array.isArray(turns) || !turns.length || pagination?.order !== "newest_first" ||
                pagination.hasMore !== (pagination.nextCursor !== null))
                throw Error("Worker turn history incomplete");
            turn = turns.at(-1);
            cursor = pagination.nextCursor;
            validateCursor(cursor, seen);
            if (cursor === null) break;
        }
        if (cursor !== null || !nonempty(turn?.id)) throw Error("Initial worker turn unavailable");

        let {items, nextItemCursor = null} = turn;
        seen.clear();
        for (let page = 0; page < 5; page++) {
            if (!Array.isArray(items) || !items.length) throw Error("Initial worker item unavailable");
            validateCursor(nextItemCursor, seen);
            if (nextItemCursor === null) break;
            const detail = await native("read_thread", {...args, itemCursor: nextItemCursor, itemLimit: 100});
            if (detail.threadId !== id || detail.turnId !== turn.id)
                throw Error("Worker item page differs from its chat or turn");
            ({items, nextItemCursor} = detail);
        }
        if (nextItemCursor !== null || !Array.isArray(items) || !items.length)
            throw Error("Initial worker item unavailable");
        const [input] = items;
        if (input?.type !== "functionCallOutput" || input.namespace !== "codex_app" || input.name !== "create_thread" ||
            input.output?.truncated !== false || typeof input.output.text !== "string")
            throw Error("Initial worker assignment unavailable");
        const assignment = /^<codex_delegation>\n  <source_thread_id>([^\n]+)<\/source_thread_id>\n  <input>([\s\S]+)<\/input>\n<\/codex_delegation>$/.exec(input.output.text);
        if (!assignment || assignment[0] !== input.output.text || !validChat(assignment[1]) || !nonempty(assignment[2]))
            throw Error("Initial worker assignment invalid");
        return input.output.text === envelope;
    }

    async function recover(record) {
        const candidates = new Map();
        let matches;
        try {
            for (const archived of [false, true]) {
                let cursor;
                for (let page = 0; page < 5; page++) {
                    const history = await native("list_threads", {mode: "history", hostId, archived, cursor, limit: 50});
                    for (const chat of history.threads) {
                        if (chat.projectId === projectId && chat.title === title && matchesChat(chat))
                            candidates.set(chat.id, chat);
                    }
                    cursor = history.nextCursor;
                    if (!cursor) break;
                }
                if (cursor) throw Error("Worker history search incomplete");
            }
            matches = [];
            for (const chat of candidates.values()) {
                if (await hasAssignment(chat)) matches.push(chat.id);
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
