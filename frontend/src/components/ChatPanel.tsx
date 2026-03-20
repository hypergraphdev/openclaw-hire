import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { ChatMessage, ChatPeer } from "../types";

// ─── ChatPanel ──────────────────────────────────────────────────────

interface ChatPanelProps {
  instanceId: string;
  agentName?: string | null;
}

export function ChatPanel({ instanceId, agentName }: ChatPanelProps) {
  const t = useT();

  // State
  const [peers, setPeers] = useState<ChatPeer[]>([]);
  const [peersLoading, setPeersLoading] = useState(true);
  const [peersError, setPeersError] = useState("");
  const [selectedPeer, setSelectedPeer] = useState<ChatPeer | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [channelId, setChannelId] = useState<string | null>(null);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [hasOlder, setHasOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const [wsStatus, setWsStatus] = useState<"connecting" | "connected" | "disconnected">("disconnected");

  // Refs
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const userScrolledUp = useRef(false);

  // ─── Load peers & auto-select current instance bot ─────────────

  useEffect(() => {
    setPeersLoading(true);
    setPeersError("");
    api.chatPeers(instanceId)
      .then((list) => {
        setPeers(list);
        if (agentName) {
          const self = list.find((p) => p.name === agentName);
          if (self) setSelectedPeer(self);
        }
      })
      .catch(() => setPeersError(t("chat.errorPeers")))
      .finally(() => setPeersLoading(false));
  }, [instanceId, agentName, t]);

  // ─── WebSocket connection ───────────────────────────────────────

  const connectWs = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    setWsStatus("connecting");

    api.chatWsTicket(instanceId)
      .then(({ ticket, ws_url }) => {
        const ws = new WebSocket(`${ws_url}?ticket=${ticket}`);
        wsRef.current = ws;

        ws.onopen = () => setWsStatus("connected");

        ws.onmessage = (ev) => {
          try {
            const data = JSON.parse(ev.data);
            if (data.type === "message" && data.message) {
              const msg: ChatMessage = data.message;
              setMessages((prev) => {
                if (prev.some((m) => m.id === msg.id)) return prev;
                return [...prev, msg];
              });
              if (!userScrolledUp.current) {
                requestAnimationFrame(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }));
              }
            } else if (data.type === "bot_online" || data.type === "bot_offline") {
              const online = data.type === "bot_online";
              setPeers((prev) =>
                prev.map((p) => (p.id === data.bot?.id ? { ...p, online } : p)),
              );
            }
          } catch { /* ignore malformed */ }
        };

        ws.onclose = () => {
          setWsStatus("disconnected");
          wsRef.current = null;
          // Auto-reconnect after 5s
          reconnectTimer.current = setTimeout(connectWs, 5000);
        };

        ws.onerror = () => ws.close();
      })
      .catch(() => {
        setWsStatus("disconnected");
        reconnectTimer.current = setTimeout(connectWs, 10000);
      });
  }, [instanceId]);

  useEffect(() => {
    connectWs();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connectWs]);

  // ─── Load messages when peer selected ───────────────────────────

  useEffect(() => {
    if (!selectedPeer || !channelId) {
      setMessages([]);
      return;
    }
    setMessagesLoading(true);
    api.chatMessages(instanceId, channelId)
      .then((res) => {
        setMessages([...res.messages].reverse());
        setHasOlder(res.has_more);
      })
      .catch(() => {})
      .finally(() => {
        setMessagesLoading(false);
        requestAnimationFrame(() => messagesEndRef.current?.scrollIntoView());
      });
  }, [instanceId, channelId, selectedPeer]);

  // ─── Load older ─────────────────────────────────────────────────

  async function loadOlder() {
    if (!channelId || loadingOlder || messages.length === 0) return;
    setLoadingOlder(true);
    const el = containerRef.current;
    const prevH = el?.scrollHeight ?? 0;
    try {
      const cursor = messages[0]?.id;
      const res = await api.chatMessages(instanceId, channelId, cursor);
      const older = [...res.messages].reverse();
      setMessages((prev) => {
        const ids = new Set(prev.map((m) => m.id));
        return [...older.filter((m) => !ids.has(m.id)), ...prev];
      });
      setHasOlder(res.has_more);
      requestAnimationFrame(() => {
        if (el) el.scrollTop = el.scrollHeight - prevH;
      });
    } catch { /* ignore */ }
    setLoadingOlder(false);
  }

  // ─── Send message ───────────────────────────────────────────────

  async function handleSend() {
    if (!selectedPeer || !input.trim() || sending) return;
    setSending(true);
    setSendError("");
    try {
      const res = await api.chatSend(instanceId, selectedPeer.name, input.trim());
      // Set channel_id from first send
      if (!channelId) {
        setChannelId(res.channel_id);
      }
      // Append sent message
      setMessages((prev) => {
        if (prev.some((m) => m.id === res.message.id)) return prev;
        return [...prev, res.message];
      });
      setInput("");
      requestAnimationFrame(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }));
    } catch {
      setSendError(t("chat.errorSend"));
    } finally {
      setSending(false);
    }
  }

  function handleScroll() {
    const el = containerRef.current;
    if (!el) return;
    userScrolledUp.current = el.scrollHeight - el.scrollTop - el.clientHeight > 100;
  }

  // ─── Render ─────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-[600px] bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      {/* Header: direct connection to instance bot */}
      <div className="shrink-0 px-4 py-3 border-b border-gray-800 flex items-center gap-3">
        <div className="flex-1 flex items-center gap-2 text-sm text-gray-200">
          {peersLoading ? (
            <span className="text-gray-500">{t("chat.loadingPeers")}</span>
          ) : selectedPeer ? (
            <>
              <span className={`inline-block h-2 w-2 rounded-full ${selectedPeer.online ? "bg-green-400" : "bg-gray-600"}`} />
              <span className="font-medium">{selectedPeer.name}</span>
              <span className="text-xs text-gray-500">
                {selectedPeer.online ? t("chat.online") : t("chat.offline")}
              </span>
            </>
          ) : (
            <span className="text-gray-500">{peersError || t("chat.noPeers")}</span>
          )}
        </div>
        <span className={`text-[10px] shrink-0 ${
          wsStatus === "connected" ? "text-green-400" :
          wsStatus === "connecting" ? "text-yellow-400" : "text-red-400"
        }`}>
          {t(`chat.${wsStatus}`)}
        </span>
      </div>

      {peersError && (
        <div className="px-4 py-2 text-xs text-red-400">{peersError}</div>
      )}

      {/* Messages area */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-3 min-h-0"
      >
        {!selectedPeer ? (
          <div className="flex items-center justify-center h-full text-gray-500 text-sm">
            {peersLoading ? t("chat.loadingPeers") : (peersError || t("chat.noPeers"))}
          </div>
        ) : messagesLoading ? (
          <div className="flex items-center justify-center h-full text-gray-500 text-sm">
            {t("chat.loadingPeers")}
          </div>
        ) : (
          <>
            {hasOlder && (
              <div className="text-center">
                <button
                  onClick={loadOlder}
                  disabled={loadingOlder}
                  className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-50"
                >
                  {loadingOlder ? "..." : t("chat.loadMore")}
                </button>
              </div>
            )}
            {messages.length === 0 && !messagesLoading && (
              <div className="text-center text-gray-500 text-sm py-8">
                {t("chat.noMessages")}
              </div>
            )}
            {messages.map((msg) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                isSelf={msg.sender_name === agentName}
              />
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input area */}
      {selectedPeer && (
        <div className="shrink-0 px-4 py-3 border-t border-gray-800">
          {sendError && <div className="text-xs text-red-400 mb-2">{sendError}</div>}
          <div className="flex gap-2">
            <input
              type="text"
              className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 outline-none focus:border-blue-500 placeholder-gray-500"
              placeholder={t("chat.inputPlaceholder")}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
              disabled={sending}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || sending}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded-lg transition-colors"
            >
              {sending ? t("chat.sending") : t("chat.send")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Message Bubble ─────────────────────────────────────────────────

function MessageBubble({ message, isSelf }: { message: ChatMessage; isSelf: boolean }) {
  const time = new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const content = extractContent(message);

  return (
    <div className={`flex flex-col ${isSelf ? "items-end" : "items-start"}`}>
      <div className="flex items-center gap-2 mb-0.5">
        <span className={`text-[11px] font-medium ${isSelf ? "text-blue-400" : "text-gray-400"}`}>
          {message.sender_name}
        </span>
        <span className="text-[10px] text-gray-600">{time}</span>
      </div>
      <div
        className={`max-w-[85%] rounded-lg px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${
          isSelf
            ? "bg-blue-600/20 border border-blue-500/30 text-gray-200"
            : "bg-gray-800 border border-gray-700 text-gray-300"
        }`}
      >
        {content}
      </div>
    </div>
  );
}

/** Extract displayable content from a message. */
function extractContent(msg: ChatMessage): string {
  // If parts exist, concatenate text/markdown parts
  if (msg.parts && msg.parts.length > 0) {
    const texts = msg.parts
      .filter((p) => p.type === "text" || p.type === "markdown")
      .map((p) => p.content ?? "");
    if (texts.length > 0) return texts.join("\n");
  }
  return msg.content || "";
}
