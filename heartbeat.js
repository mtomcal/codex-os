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
    for (const job of pulse?.workers_to_archive ?? []) {
        const {worker, key, host} = job;
        try {
            if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(key) ||
                !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(worker) || host !== "local")
                throw Error("Invalid cleanup candidate");
            if (!await archived(worker, host)) {
                const [text] = await native(tools.mcp__codex_app__wait_threads, {
                    targets: [{threadId: worker, hostId: host}], timeoutMs: 0
                });
                const poll = JSON.parse(text).polls?.[0];
                if (poll?.thread?.id !== worker || poll.thread.status?.type !== "idle" ||
                    !["completed", "failed", "interrupted"].includes(poll.latestTurn?.status)) continue;
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
