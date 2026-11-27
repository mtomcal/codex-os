// Apply the same malformed history mutations to each desktop entry point.
module.exports = {
    historyCases: [
        ["false list cursor", page => { page.nextCursor = false; }],
        ["omitted list cursor", page => { delete page.nextCursor; }],
        ["empty list cursor", page => { page.nextCursor = ""; }],
        ["non-array list", page => { page.threads = {}; }],
        ["unidentifiable list entry", page => { delete page.threads.at(-1).id; }],
        ["omitted project in a list entry", page => { delete page.threads.at(-1).projectId; }],
        ["omitted title in a list entry", page => { delete page.threads.at(-1).title; }],
        ["duplicate list entry", page => { page.threads.push({...page.threads[0], title: "Conflicting title"}); }],
    ],
    turnCases: [
        ["mismatched title", detail => { detail.thread.title = "Other worker"; }],
        ["mismatched project", detail => { detail.thread.projectId = "other-project"; }],
        ["omitted turn cursor", detail => { delete detail.page.nextCursor; }],
        ["contradictory turn pagination", detail => { detail.page.hasMore = true; }],
        ["wrong turn order", detail => { detail.page.order = "oldest_first"; }],
        ["malformed item cursor", detail => { detail.turns[0].nextItemCursor = false; }],
        ["repeated turn", detail => { detail.turns.push(detail.turns[0]); }],
        ["malformed initial item", detail => { detail.turns[0].items[0].type = "userMessage"; }],
        ["malformed delegation envelope", detail => { detail.turns[0].items[0].output.text = "Unreadable assignment"; }],
    ],
    itemCases: [
        ["foreign chat and turn", page => {
            page.threadId = "99999999-9999-4999-8999-999999999999";
            page.turnId = "foreign-turn";
        }],
        ["omitted item page cursor", page => { delete page.nextItemCursor; }],
        ["repeated item cursor", page => { page.nextItemCursor = "older-items"; }],
        ["repeated item", page => { page.items[0].id = "newer-item"; }],
        ["empty item page", page => { page.items = []; }],
    ],
};
