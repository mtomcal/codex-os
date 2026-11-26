// Run in the desktop code-mode tool runtime with the bot project as its working directory.
(async function heartbeat(tools, workdir) {
    async function cli(cmd) {
        let result = await tools.exec_command({cmd: "python3 ../../codexos.py " + cmd, workdir});
        let output = result.output;
        while (result.session_id && result.exit_code == null) {
            result = await tools.write_stdin({session_id: result.session_id, chars: ""});
            output += result.output;
        }
        if (result.exit_code !== 0) throw Error(output.trim() || "Fleet command failed");
        return output.trim() ? JSON.parse(output) : null;
    }
    async function native(tool, args) {
        const reply = await tool(args);
        if (reply.isError) throw Error("Native Codex operation failed");
        return reply.content.map(item => item.text).filter(Boolean);
    }
    async function workerSnapshots(targets) {
        const [text] = await native(tools.mcp__codex_app__wait_threads, {targets, timeoutMs: 0});
        return JSON.parse(text);
    }
    function terminalTurn(snapshot, {worker, host}) {
        if (snapshot?.activityComplete === false ||
            snapshot?.errors?.some(error => error.threadId === worker && error.hostId === host)) return;
        const matches = snapshot?.polls?.filter(poll => poll.thread?.id === worker && poll.thread.hostId === host);
        if (matches?.length !== 1) return;
        const [poll] = matches;
        if (poll.activityComplete === false || poll.thread.status?.type !== "idle") return;
        const turn = poll.latestTurn;
        if (turn?.id && Number.isFinite(turn.completedAt) &&
            ["completed", "failed", "interrupted"].includes(turn.status)) return turn;
    }
    async function archived(id, hostId) {
        let cursor;
        do {
            const [text] = await native(tools.mcp__codex_app__list_archived_threads, {hostId, limit: 50, cursor});
            const page = JSON.parse(text);
            if (page.threads.some(t => t.id === id && t.hostId === hostId)) return true;
            cursor = page.nextCursor;
        } while (cursor);
        return false;
    }

    const pulse = await cli("heartbeat");
    if (!pulse) return pulse;
    pulse.workers_to_review = [];
    const pendingReview = pulse.workers_to_check.filter(job => job.worker && job.host && !job.delivery);
    if (pendingReview.length) {
        try {
            const snapshot = await workerSnapshots(pendingReview.map(({worker, host}) => ({threadId: worker, hostId: host})));
            for (const job of pendingReview) {
                const turn = terminalTurn(snapshot, job);
                if (turn) pulse.workers_to_review.push({...job, turn_id: turn.id, turn_status: turn.status});
            }
        } catch {
            pulse.worker_status_pending = true;
        }
    }
    for (const job of pulse.workers_to_archive ?? []) {
        const {worker, key, host} = job;
        try {
            if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(key) ||
                !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(worker) || host !== "local")
                throw Error("Invalid cleanup candidate");
            if (!await archived(worker, host)) {
                const snapshot = await workerSnapshots([{threadId: worker, hostId: host}]);
                if (!terminalTurn(snapshot, job)) continue;
                await native(tools.mcp__codex_app__set_thread_archived, {threadId: worker, hostId: host, archived: true});
                if (!await archived(worker, host)) throw Error("Archive confirmation pending");
            }
            await cli("dispatch cleaned " + key + " --evidence 'Confirmed in native local archive: " + worker + "'");
            pulse.workers_to_check = pulse.workers_to_check.filter(row => row.key !== key);
        } catch (error) {
            job.cleanup_pending = String(error.message || error);
        }
    }
    return pulse;
})
