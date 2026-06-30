// Admin copilot chat UI. jQuery + Bootstrap (no framework). Sends messages, polls for new
// CopilotDiscussionItem rows (background agent), and handles approve/reject of proposed actions.
$(function () {
    var $layout = $(".copilot-layout");
    if (!$layout.length) return;

    var urls = {
        newDiscussion: $layout.data("url-new"),
        message: $layout.data("url-message"),
        approve: $layout.data("url-approve"),
        items: $layout.data("url-items"),
    };
    var discussionUuid = $layout.data("discussion-uuid");
    var csrfToken = $("[name=csrfmiddlewaretoken]").val();

    var $messages = $("#copilot-messages");
    var $form = $("#copilot-form");
    var $text = $("#copilot-text");
    var $send = $("#copilot-send");
    var $typing = $("#copilot-typing");
    var $error = $("#copilot-error");

    var pollTimer = null;
    var lastPosition = computeLastPosition();

    function computeLastPosition() {
        var max = -1;
        $messages.find(".copilot-item").each(function () {
            var p = parseInt($(this).data("position"), 10);
            if (!isNaN(p) && p > max) max = p;
        });
        return max;
    }

    function scrollToBottom() {
        $messages.scrollTop($messages[0].scrollHeight);
    }

    function post(url, data) {
        return $.ajax({
            url: url,
            method: "POST",
            headers: { "X-CSRFToken": csrfToken },
            data: data,
        });
    }

    function setBusy(busy) {
        $send.prop("disabled", busy);
        $typing.toggleClass("d-none", !busy);
    }

    function startPolling() {
        if (pollTimer) return;
        setBusy(true);
        pollTimer = setInterval(pollOnce, 1500);
    }

    function stopPolling() {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        setBusy(false);
    }

    function pollOnce() {
        $.getJSON(urls.items, { since: lastPosition }).done(function (resp) {
            if (resp.html && resp.html.trim()) {
                $messages.append(resp.html);
                lastPosition = resp.last_position;
                scrollToBottom();
            }
            if (resp.status === "error") {
                $error.text(resp.error_message || "Une erreur est survenue.").removeClass("d-none");
            }
            // Keep polling only while the agent is actively running.
            if (resp.status !== "running") {
                stopPolling();
            }
        }).fail(function () {
            // Transient failure: keep polling, the agent may still be working.
        });
    }

    // Send a message (or create a new discussion if we are on the empty page).
    $form.on("submit", function (e) {
        e.preventDefault();
        var text = $.trim($text.val());
        if (!text) return;

        if (!discussionUuid) {
            setBusy(true);
            post(urls.newDiscussion, { text: text }).done(function (resp) {
                window.location = resp.redirect;
            }).fail(function () {
                setBusy(false);
                alert("Impossible de démarrer la discussion.");
            });
            return;
        }

        $error.addClass("d-none");
        post(urls.message, { text: text }).done(function () {
            $text.val("");
            // Optimistically show the user message immediately, then poll for the agent.
            lastPosition = computeLastPosition();
            startPolling();
            pollOnce();
        }).fail(function (xhr) {
            if (xhr.status === 409) {
                alert("Le copilote est déjà en train de répondre.");
            } else {
                alert("Échec de l'envoi du message.");
            }
        });
    });

    // Approve / reject a proposed action.
    $messages.on("click", ".copilot-approve", function () {
        var $btn = $(this);
        var itemUuid = $btn.data("item-uuid");
        var decision = $btn.data("decision");
        $btn.closest(".copilot-proposed-actions").find("button").prop("disabled", true);
        post(urls.approve, { item_uuid: itemUuid, decision: decision }).done(function () {
            lastPosition = computeLastPosition();
            startPolling();
            pollOnce();
        }).fail(function () {
            $btn.closest(".copilot-proposed-actions").find("button").prop("disabled", false);
            alert("Échec de la validation.");
        });
    });

    // Submit on Enter (Shift+Enter for newline).
    $text.on("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            $form.submit();
        }
    });

    // If the discussion was already running/awaiting when the page loaded, resume polling.
    if ($layout.data("status") === "running") {
        startPolling();
    }
    scrollToBottom();
});
