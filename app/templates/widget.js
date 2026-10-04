(function() {
    // Avoid double initialization
    if (window.__DISPATCH_WIDGET_INITIALIZED__) return;
    window.__DISPATCH_WIDGET_INITIALIZED__ = true;

    var TENANT_SLUG = "{{ tenant_slug }}";
    var TENANT_NAME = "{{ tenant_name }}";
    var TENANT_PHONE = "{{ tenant_phone }}";
    var BASE_URL = "{{ base_url }}";

    // Inject styles
    var style = document.createElement("style");
    style.id = "dispatch-widget-styles";
    style.textContent = `
        #dispatch-widget-root {
            position: fixed;
            bottom: 24px;
            right: 24px;
            z-index: 999999;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: #F8FAFC;
        }
        #dispatch-widget-bubble {
            display: flex;
            align-items: center;
            gap: 10px;
            background: linear-gradient(135deg, #0284C7 0%, #0369A1 100%);
            color: #FFFFFF;
            padding: 12px 20px;
            border-radius: 9999px;
            box-shadow: 0 10px 25px -5px rgba(2, 132, 199, 0.4), 0 8px 10px -6px rgba(2, 132, 199, 0.2);
            cursor: pointer;
            transition: all 0.2s ease-in-out;
            font-weight: 600;
            font-size: 14px;
            border: 1px solid rgba(255, 255, 255, 0.15);
            user-select: none;
        }
        #dispatch-widget-bubble:hover {
            transform: translateY(-2px);
            box-shadow: 0 14px 28px -5px rgba(2, 132, 199, 0.5);
            background: linear-gradient(135deg, #0EA5E9 0%, #0284C7 100%);
        }
        .dispatch-pulse-dot {
            width: 10px;
            height: 10px;
            background-color: #10B981;
            border-radius: 50%;
            position: relative;
        }
        .dispatch-pulse-dot::after {
            content: '';
            position: absolute;
            width: 100%;
            height: 100%;
            top: 0;
            left: 0;
            background-color: #10B981;
            border-radius: 50%;
            animation: dispatch-pulse 1.8s infinite cubic-bezier(0, 0, 0.2, 1);
        }
        @keyframes dispatch-pulse {
            0% { transform: scale(1); opacity: 1; }
            100% { transform: scale(2.8); opacity: 0; }
        }
        #dispatch-widget-window {
            position: fixed;
            bottom: 84px;
            right: 24px;
            width: 380px;
            max-width: calc(100vw - 32px);
            height: 580px;
            max-height: calc(100vh - 110px);
            background-color: #0B0F19;
            border: 1px solid #1E293B;
            border-radius: 16px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
            display: none;
            flex-direction: column;
            overflow: hidden;
            z-index: 1000000;
            animation: dispatch-slide-up 0.25s ease-out;
        }
        @keyframes dispatch-slide-up {
            from { opacity: 0; transform: translateY(12px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .dispatch-header {
            background: #111827;
            padding: 16px;
            border-bottom: 1px solid #1F2937;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .dispatch-header-title {
            font-size: 15px;
            font-weight: 700;
            color: #FFFFFF;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .dispatch-header-sub {
            font-size: 12px;
            color: #94A3B8;
            margin-top: 2px;
        }
        .dispatch-close-btn {
            background: none;
            border: none;
            color: #94A3B8;
            font-size: 20px;
            cursor: pointer;
            padding: 4px 8px;
            border-radius: 6px;
            line-height: 1;
        }
        .dispatch-close-btn:hover {
            color: #FFFFFF;
            background: #1F2937;
        }
        .dispatch-quick-actions {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            padding: 12px 14px;
            background: #0D1322;
            border-bottom: 1px solid #1F2937;
        }
        .dispatch-action-card {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 10px 8px;
            border-radius: 10px;
            text-decoration: none;
            font-size: 11px;
            font-weight: 600;
            text-align: center;
            transition: all 0.15s ease;
            cursor: pointer;
            border: 1px solid transparent;
        }
        .dispatch-call-card {
            background: rgba(239, 68, 68, 0.12);
            color: #F87171;
            border-color: rgba(239, 68, 68, 0.3);
        }
        .dispatch-call-card:hover {
            background: rgba(239, 68, 68, 0.22);
            border-color: #EF4444;
            color: #FECACA;
        }
        .dispatch-quote-card {
            background: rgba(14, 165, 233, 0.12);
            color: #38BDF8;
            border-color: rgba(14, 165, 233, 0.3);
        }
        .dispatch-quote-card:hover {
            background: rgba(14, 165, 233, 0.22);
            border-color: #0EA5E9;
            color: #BAE6FD;
        }
        .dispatch-action-card svg {
            width: 18px;
            height: 18px;
            margin-bottom: 4px;
        }
        .dispatch-chat-messages {
            flex: 1;
            padding: 14px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 12px;
            background: #0B0F19;
        }
        .dispatch-msg {
            max-width: 85%;
            padding: 10px 14px;
            border-radius: 14px;
            font-size: 13px;
            line-height: 1.45;
            word-break: break-word;
        }
        .dispatch-msg-bot {
            align-self: flex-start;
            background: #1E293B;
            color: #F1F5F9;
            border-bottom-left-radius: 4px;
            border: 1px solid #334155;
        }
        .dispatch-msg-user {
            align-self: flex-end;
            background: #0284C7;
            color: #FFFFFF;
            border-bottom-right-radius: 4px;
        }
        .dispatch-tracking-badge {
            display: inline-block;
            margin-top: 8px;
            padding: 8px 12px;
            background: rgba(16, 185, 129, 0.15);
            border: 1px solid rgba(16, 185, 129, 0.4);
            border-radius: 8px;
            color: #34D399;
            text-decoration: none;
            font-weight: 600;
            font-size: 12px;
        }
        .dispatch-tracking-badge:hover {
            background: rgba(16, 185, 129, 0.25);
            color: #A7F3D0;
        }
        .dispatch-chat-input-area {
            padding: 12px;
            background: #111827;
            border-top: 1px solid #1F2937;
            display: flex;
            gap: 8px;
        }
        .dispatch-chat-input {
            flex: 1;
            background: #0B0F19;
            border: 1px solid #374151;
            border-radius: 8px;
            padding: 10px 12px;
            color: #FFFFFF;
            font-size: 13px;
            outline: none;
        }
        .dispatch-chat-input:focus {
            border-color: #0284C7;
        }
        .dispatch-send-btn {
            background: #0284C7;
            border: none;
            border-radius: 8px;
            color: #FFFFFF;
            width: 38px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: background 0.15s;
        }
        .dispatch-send-btn:hover {
            background: #0369A1;
        }
        .dispatch-typing {
            align-self: flex-start;
            padding: 8px 14px;
            background: #1E293B;
            border-radius: 12px;
            display: none;
            gap: 4px;
            align-items: center;
        }
        .dispatch-dot {
            width: 6px;
            height: 6px;
            background: #94A3B8;
            border-radius: 50%;
            animation: dispatch-bounce 1.4s infinite ease-in-out both;
        }
        .dispatch-dot:nth-child(1) { animation-delay: -0.32s; }
        .dispatch-dot:nth-child(2) { animation-delay: -0.16s; }
        @keyframes dispatch-bounce {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1.0); }
        }
    `;
    document.head.appendChild(style);

    // Create root container
    var root = document.createElement("div");
    root.id = "dispatch-widget-root";

    var telHref = TENANT_PHONE ? "tel:" + TENANT_PHONE : "javascript:alert('Direct phone dispatch connecting...');";

    root.innerHTML = `
        <div id="dispatch-widget-bubble" role="button" aria-label="Open emergency dispatch widget">
            <span class="dispatch-pulse-dot"></span>
            <span>24/7 AI Dispatch</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
            </svg>
        </div>

        <div id="dispatch-widget-window">
            <div class="dispatch-header">
                <div>
                    <div class="dispatch-header-title">
                        <span class="dispatch-pulse-dot"></span>
                        <span>` + TENANT_NAME + `</span>
                    </div>
                    <div class="dispatch-header-sub">Instant AI Emergency Dispatch & Estimates</div>
                </div>
                <button class="dispatch-close-btn" id="dispatch-close-btn" aria-label="Close widget">&times;</button>
            </div>

            <div class="dispatch-quick-actions">
                <a href="` + telHref + `" class="dispatch-action-card dispatch-call-card" id="dispatch-tap-call">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path>
                    </svg>
                    <span>1-Tap Emergency Call</span>
                </a>
                <div class="dispatch-action-card dispatch-quote-card" id="dispatch-snap-photo-btn">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
                        <circle cx="12" cy="13" r="4"></circle>
                    </svg>
                    <span>Snap Photo for Quote</span>
                </div>
            </div>

            <div class="dispatch-chat-messages" id="dispatch-chat-messages">
                <div class="dispatch-msg dispatch-msg-bot">
                    Hello! I'm the 24/7 AI Dispatcher for <strong>` + TENANT_NAME + `</strong>. Describe your issue or emergency below, and I'll route a technician immediately.
                </div>
                <div class="dispatch-typing" id="dispatch-typing">
                    <div class="dispatch-dot"></div>
                    <div class="dispatch-dot"></div>
                    <div class="dispatch-dot"></div>
                </div>
            </div>

            <div class="dispatch-chat-input-area">
                <input type="text" class="dispatch-chat-input" id="dispatch-chat-input" placeholder="Type your message or emergency..." autocomplete="off">
                <button class="dispatch-send-btn" id="dispatch-send-btn" aria-label="Send">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="22" y1="2" x2="11" y2="13"></line>
                        <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                    </svg>
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(root);

    // Event handlers
    var bubble = document.getElementById("dispatch-widget-bubble");
    var win = document.getElementById("dispatch-widget-window");
    var closeBtn = document.getElementById("dispatch-close-btn");
    var chatInput = document.getElementById("dispatch-chat-input");
    var sendBtn = document.getElementById("dispatch-send-btn");
    var messagesContainer = document.getElementById("dispatch-chat-messages");
    var typingIndicator = document.getElementById("dispatch-typing");
    var snapPhotoBtn = document.getElementById("dispatch-snap-photo-btn");

    function toggleWidget() {
        var isOpen = win.style.display === "flex";
        win.style.display = isOpen ? "none" : "flex";
        if (!isOpen) {
            chatInput.focus();
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    }

    bubble.addEventListener("click", toggleWidget);
    closeBtn.addEventListener("click", toggleWidget);

    // Snap photo button: requests modal or opens intake view
    snapPhotoBtn.addEventListener("click", function() {
        // Send a trigger prompt to chat to initiate intake or open window
        appendMessage("I would like to snap a photo of my equipment for an instant quote.", "user");
        handleSendMessage("I want to upload an equipment photo for an instant quote");
    });

    function appendMessage(text, sender, trackingUrl, intakeUrl) {
        var msgDiv = document.createElement("div");
        msgDiv.className = "dispatch-msg " + (sender === "user" ? "dispatch-msg-user" : "dispatch-msg-bot");
        
        var content = document.createElement("div");
        content.textContent = text;
        msgDiv.appendChild(content);

        if (trackingUrl) {
            var trackLink = document.createElement("a");
            trackLink.href = trackingUrl;
            trackLink.target = "_blank";
            trackLink.className = "dispatch-tracking-badge";
            trackLink.innerHTML = "📍 Track Dispatched Technician Live &rarr;";
            msgDiv.appendChild(trackLink);
        }

        if (intakeUrl) {
            var intakeLink = document.createElement("a");
            intakeLink.href = intakeUrl;
            intakeLink.target = "_blank";
            intakeLink.className = "dispatch-tracking-badge";
            intakeLink.style.borderColor = "rgba(14, 165, 233, 0.4)";
            intakeLink.style.color = "#38BDF8";
            intakeLink.innerHTML = "📸 Open Camera Equipment Scanner &rarr;";
            msgDiv.appendChild(intakeLink);
        }

        messagesContainer.insertBefore(msgDiv, typingIndicator);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    async function handleSendMessage(overrideText) {
        var text = overrideText || chatInput.value.trim();
        if (!text) return;

        if (!overrideText) {
            appendMessage(text, "user");
            chatInput.value = "";
        }

        typingIndicator.style.display = "flex";
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        try {
            var response = await fetch(BASE_URL + "/api/v1/widget/" + TENANT_SLUG + "/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: text })
            });

            typingIndicator.style.display = "none";

            if (!response.ok) {
                appendMessage("Thank you for your message. We have alerted our dispatch team.", "bot");
                return;
            }

            var data = await response.json();
            appendMessage(data.response_text, "bot", data.tracking_url, data.intake_url);
        } catch (err) {
            typingIndicator.style.display = "none";
            appendMessage("Thank you for reaching out. Our emergency line is on standby at " + (TENANT_PHONE || "our main number") + ".", "bot");
        }
    }

    sendBtn.addEventListener("click", function() { handleSendMessage(); });
    chatInput.addEventListener("keydown", function(e) {
        if (e.key === "Enter") {
            handleSendMessage();
        }
    });

})();
