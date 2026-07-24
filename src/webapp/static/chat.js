(function () {
  const log = document.getElementById("chat-log");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("question");
  const pidA = document.getElementById("pid_a");
  const pidB = document.getElementById("pid_b");

  function addMsg(cls, html) {
    const div = document.createElement("div");
    div.className = "chat-msg " + cls;
    div.innerHTML = html;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    addMsg("chat-user", escapeHtml(question));
    input.value = "";
    const pending = addMsg("chat-answer", "<em>Thinking…</em>");

    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pid_a: pidA.value, pid_b: pidB.value, question }),
      });
      const data = await resp.json();
      const citations = (data.citations || [])
        .filter((c, i, arr) => arr.indexOf(c) === i)
        .map((c) => `<span class="chat-citation">${escapeHtml(c)}</span>`)
        .join("");
      pending.innerHTML =
        escapeHtml(data.answer) +
        `<div class="chat-meta">grounded=${data.grounded} · model=${escapeHtml(data.model || "mock")} · ` +
        `tokens=${(data.input_tokens || 0) + (data.output_tokens || 0)} · cost=$${(data.cost_usd || 0).toFixed(6)} · ` +
        `request=${escapeHtml(data.request_id || "")}</div>` +
        (citations ? `<div class="chat-meta">${citations}</div>` : "");
    } catch (err) {
      pending.innerHTML = "Error: " + escapeHtml(err.message);
    }
  });
})();
