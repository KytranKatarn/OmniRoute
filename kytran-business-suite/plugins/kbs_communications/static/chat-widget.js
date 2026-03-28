/**
 * KBS Chat Widget — embeddable floating chat bubble with REST polling.
 *
 * Usage:
 *   <script src="/communications/static/chat-widget.js"
 *           data-tenant-id="1"
 *           data-api-base="/communications"></script>
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var TENANT_ID = script ? script.getAttribute("data-tenant-id") || "1" : "1";
  var API_BASE = script ? script.getAttribute("data-api-base") || "/communications" : "/communications";
  var POLL_INTERVAL = 3000;

  var conversationId = null;
  var pollTimer = null;
  var lastMessageTs = null;

  function createWidget() {
    var style = document.createElement("style");
    style.textContent = [
      ".kbs-chat-bubble{position:fixed;bottom:24px;right:24px;width:56px;height:56px;",
      "border-radius:50%;background:#0ea5e9;color:#fff;display:flex;align-items:center;",
      "justify-content:center;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.25);",
      "z-index:9999;font-size:24px;transition:transform .2s}",
      ".kbs-chat-bubble:hover{transform:scale(1.1)}",
      ".kbs-chat-panel{position:fixed;bottom:90px;right:24px;width:360px;max-height:480px;",
      "background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,.2);",
      "display:none;flex-direction:column;z-index:9999;overflow:hidden;font-family:sans-serif}",
      ".kbs-chat-panel.open{display:flex}",
      ".kbs-chat-header{background:#0ea5e9;color:#fff;padding:12px 16px;font-weight:600;",
      "display:flex;justify-content:space-between;align-items:center}",
      ".kbs-chat-header button{background:none;border:none;color:#fff;cursor:pointer;font-size:18px}",
      ".kbs-chat-messages{flex:1;overflow-y:auto;padding:12px;min-height:200px;max-height:320px}",
      ".kbs-chat-msg{margin-bottom:8px;padding:8px 12px;border-radius:8px;max-width:80%;",
      "font-size:14px;line-height:1.4}",
      ".kbs-chat-msg.visitor{background:#e0f2fe;margin-left:auto;text-align:right}",
      ".kbs-chat-msg.agent,.kbs-chat-msg.system{background:#f1f5f9}",
      ".kbs-chat-input{display:flex;border-top:1px solid #e2e8f0;padding:8px}",
      ".kbs-chat-input input{flex:1;border:1px solid #cbd5e1;border-radius:6px;padding:8px;",
      "font-size:14px;outline:none}",
      ".kbs-chat-input button{margin-left:8px;background:#0ea5e9;color:#fff;border:none;",
      "border-radius:6px;padding:8px 16px;cursor:pointer;font-size:14px}",
      ".kbs-chat-pre{padding:16px;text-align:center}",
      ".kbs-chat-pre input{display:block;width:90%;margin:8px auto;padding:8px;",
      "border:1px solid #cbd5e1;border-radius:6px;font-size:14px}",
      ".kbs-chat-pre button{margin-top:8px;background:#0ea5e9;color:#fff;border:none;",
      "border-radius:6px;padding:10px 24px;cursor:pointer;font-size:14px}"
    ].join("\n");
    document.head.appendChild(style);

    // Bubble
    var bubble = document.createElement("div");
    bubble.className = "kbs-chat-bubble";
    bubble.textContent = "\uD83D\uDCAC";
    bubble.addEventListener("click", togglePanel);
    document.body.appendChild(bubble);

    // Panel
    var panel = document.createElement("div");
    panel.className = "kbs-chat-panel";
    panel.id = "kbs-chat-panel";

    // Header
    var header = document.createElement("div");
    header.className = "kbs-chat-header";
    var title = document.createElement("span");
    title.textContent = "Chat with us";
    var closeBtn = document.createElement("button");
    closeBtn.textContent = "\u00D7";
    closeBtn.addEventListener("click", function () {
      panel.classList.remove("open");
    });
    header.appendChild(title);
    header.appendChild(closeBtn);
    panel.appendChild(header);

    // Pre-chat form
    var pre = document.createElement("div");
    pre.className = "kbs-chat-pre";
    pre.id = "kbs-chat-pre";
    var preP = document.createElement("p");
    preP.textContent = "Enter your name to start chatting:";
    var nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.id = "kbs-chat-name";
    nameInput.placeholder = "Your name";
    var emailInput = document.createElement("input");
    emailInput.type = "email";
    emailInput.id = "kbs-chat-email";
    emailInput.placeholder = "Email (optional)";
    var startBtn = document.createElement("button");
    startBtn.textContent = "Start Chat";
    startBtn.addEventListener("click", startChat);
    pre.appendChild(preP);
    pre.appendChild(nameInput);
    pre.appendChild(emailInput);
    pre.appendChild(startBtn);
    panel.appendChild(pre);

    // Messages area
    var messagesDiv = document.createElement("div");
    messagesDiv.className = "kbs-chat-messages";
    messagesDiv.id = "kbs-chat-messages";
    messagesDiv.style.display = "none";
    panel.appendChild(messagesDiv);

    // Input area
    var inputDiv = document.createElement("div");
    inputDiv.className = "kbs-chat-input";
    inputDiv.id = "kbs-chat-input";
    inputDiv.style.display = "none";
    var textInput = document.createElement("input");
    textInput.type = "text";
    textInput.id = "kbs-chat-text";
    textInput.placeholder = "Type a message...";
    textInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") sendMessage();
    });
    var sendBtn = document.createElement("button");
    sendBtn.textContent = "Send";
    sendBtn.addEventListener("click", sendMessage);
    inputDiv.appendChild(textInput);
    inputDiv.appendChild(sendBtn);
    panel.appendChild(inputDiv);

    document.body.appendChild(panel);
  }

  function togglePanel() {
    document.getElementById("kbs-chat-panel").classList.toggle("open");
  }

  function apiPost(path, body) {
    return fetch(API_BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  function apiGet(path) {
    return fetch(API_BASE + path).then(function (r) { return r.json(); });
  }

  function startChat() {
    var name = document.getElementById("kbs-chat-name").value.trim() || "Visitor";
    var email = document.getElementById("kbs-chat-email").value.trim();

    apiPost("/api/chat/start", {
      tenant_id: parseInt(TENANT_ID),
      visitor_name: name,
      visitor_email: email || null,
    }).then(function (data) {
      conversationId = data.id;
      document.getElementById("kbs-chat-pre").style.display = "none";
      document.getElementById("kbs-chat-messages").style.display = "block";
      document.getElementById("kbs-chat-input").style.display = "flex";
      pollMessages();
      pollTimer = setInterval(pollMessages, POLL_INTERVAL);
    });
  }

  function sendMessage() {
    var input = document.getElementById("kbs-chat-text");
    var text = input.value.trim();
    if (!text || !conversationId) return;
    input.value = "";

    apiPost("/api/chat/" + conversationId + "/message", {
      tenant_id: parseInt(TENANT_ID),
      sender_type: "visitor",
      content: text,
      sender_name: document.getElementById("kbs-chat-name").value.trim() || "Visitor",
    }).then(function () {
      pollMessages();
    });
  }

  function pollMessages() {
    if (!conversationId) return;
    var url = "/api/chat/" + conversationId + "/messages?tenant_id=" + TENANT_ID;
    if (lastMessageTs) url += "&since=" + encodeURIComponent(lastMessageTs);

    apiGet(url).then(function (data) {
      var container = document.getElementById("kbs-chat-messages");
      (data.messages || []).forEach(function (msg) {
        var div = document.createElement("div");
        div.className = "kbs-chat-msg " + msg.sender_type;
        div.textContent = msg.content;
        container.appendChild(div);
        lastMessageTs = msg.created_at;
      });
      container.scrollTop = container.scrollHeight;
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createWidget);
  } else {
    createWidget();
  }
})();
