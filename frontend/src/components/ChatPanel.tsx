import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { ChatInfo, ChatMessage } from "../types";

// ─── ChatPanel ──────────────────────────────────────────────────────

interface ChatPanelProps {
  instanceId: string;
  agentName?: string | null;
  expanded?: boolean;
  onToggleExpand?: () => void;
}

export function ChatPanel({ instanceId, expanded, onToggleExpand }: ChatPanelProps) {
  const t = useT();

  // State
  const [chatInfo, setChatInfo] = useState<ChatInfo | null>(null);
  const [infoLoading, setInfoLoading] = useState(true);
  const [infoError, setInfoError] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [channelId, setChannelId] = useState<string | null>(null);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [hasOlder, setHasOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const [wsStatus, setWsStatus] = useState<"connecting" | "connected" | "disconnected">("disconnected");
  const [botTyping, setBotTyping] = useState(false);

  // Refs
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const userScrolledUp = useRef(false);

  // ─── Load chat info (target bot + admin bot identity) ───────────

  useEffect(() => {
    setInfoLoading(true);
    setInfoError("");
    api.chatInfo(instanceId)
      .then((info) => {
        setChatInfo(info);
        // Auto-load history if DM channel already exists
        if (info.dm_channel_id) {
          setChannelId(info.dm_channel_id);
        }
      })
      .catch(() => setInfoError(t("chat.errorPeers")))
      .finally(() => setInfoLoading(false));
  }, [instanceId, t]);

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
            // Typing indicator from hub
            if (data.type === "typing") {
              setBotTyping(true);
              clearTimeout(typingTimer.current);
              typingTimer.current = setTimeout(() => setBotTyping(false), 5000);
              return;
            }
            if (data.type === "message" && data.message) {
              // Bot replied, stop typing indicator
              setBotTyping(false);
              clearTimeout(typingTimer.current);
              const msg: ChatMessage = data.message;
              setMessages((prev) => {
                if (prev.some((m) => m.id === msg.id)) return prev;
                return [...prev, msg];
              });
              if (!userScrolledUp.current) {
                requestAnimationFrame(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }));
              }
            }
          } catch { /* ignore malformed */ }
        };

        ws.onclose = () => {
          setWsStatus("disconnected");
          wsRef.current = null;
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
      clearTimeout(typingTimer.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connectWs]);

  // ─── Load messages when channel known ─────────────────────────

  useEffect(() => {
    if (!channelId) {
      setMessages([]);
      return;
    }
    setMessagesLoading(true);
    api.chatMessages(instanceId, channelId)
      .then((res) => {
        setMessages([...res.messages].sort((a, b) => a.created_at - b.created_at));
        setHasOlder(res.has_more);
      })
      .catch(() => {})
      .finally(() => {
        setMessagesLoading(false);
        requestAnimationFrame(() => messagesEndRef.current?.scrollIntoView());
      });
  }, [instanceId, channelId]);

  // ─── Load older ─────────────────────────────────────────────────

  async function loadOlder() {
    if (!channelId || loadingOlder || messages.length === 0) return;
    setLoadingOlder(true);
    const el = containerRef.current;
    const prevH = el?.scrollHeight ?? 0;
    try {
      const cursor = messages[0]?.id;
      const res = await api.chatMessages(instanceId, channelId, cursor);
      const older = [...res.messages].sort((a, b) => a.created_at - b.created_at);
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
    if (!chatInfo || !input.trim() || sending) return;
    setSending(true);
    setSendError("");
    // Start typing indicator immediately after sending
    setBotTyping(true);
    clearTimeout(typingTimer.current);
    typingTimer.current = setTimeout(() => setBotTyping(false), 30000);
    try {
      const res = await api.chatSend(instanceId, input.trim());
      if (!channelId) {
        setChannelId(res.channel_id);
      }
      setMessages((prev) => {
        if (prev.some((m) => m.id === res.message.id)) return prev;
        return [...prev, res.message];
      });
      setInput("");
      requestAnimationFrame(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }));
    } catch {
      setSendError(t("chat.errorSend"));
      setBotTyping(false);
      clearTimeout(typingTimer.current);
    } finally {
      setSending(false);
    }
  }

  function handleScroll() {
    const el = containerRef.current;
    if (!el) return;
    userScrolledUp.current = el.scrollHeight - el.scrollTop - el.clientHeight > 100;
  }

  const adminBotId = chatInfo?.admin_bot_id || "";

  // ─── Render ─────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-[600px] bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      {/* Header: direct connection to instance bot */}
      <div className="shrink-0 px-4 py-3 border-b border-gray-800 flex items-center gap-3">
        <div className="flex-1 flex items-center gap-2 text-sm text-gray-200">
          {infoLoading ? (
            <span className="text-gray-500">{t("chat.loadingPeers")}</span>
          ) : chatInfo ? (
            <>
              <span className={`inline-block h-2 w-2 rounded-full ${chatInfo.target_online ? "bg-green-400" : "bg-gray-600"}`} />
              <span className="font-medium">{chatInfo.target_name}</span>
              <span className="text-xs text-gray-500">
                {chatInfo.target_online ? t("chat.online") : t("chat.offline")}
              </span>
            </>
          ) : (
            <span className="text-gray-500">{infoError || t("chat.noPeers")}</span>
          )}
        </div>
        <span className={`text-[10px] shrink-0 ${
          wsStatus === "connected" ? "text-green-400" :
          wsStatus === "connecting" ? "text-yellow-400" : "text-red-400"
        }`}>
          {t(`chat.${wsStatus}`)}
        </span>
        {/* Expand / collapse button */}
        {onToggleExpand && (
          <button
            onClick={onToggleExpand}
            className="text-gray-500 hover:text-gray-300 transition-colors p-1"
            title={expanded ? t("chat.collapse") : t("chat.expand")}
          >
            {expanded ? (
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5l5.25 5.25" />
              </svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
              </svg>
            )}
          </button>
        )}
      </div>

      {infoError && (
        <div className="px-4 py-2 text-xs text-red-400">{infoError}</div>
      )}

      {/* Messages area */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-3 min-h-0"
      >
        {!chatInfo ? (
          <div className="flex items-center justify-center h-full text-gray-500 text-sm">
            {infoLoading ? t("chat.loadingPeers") : (infoError || t("chat.noPeers"))}
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
                isSelf={msg.sender_id === adminBotId}
              />
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
        {/* Typing indicator — outside message loading condition so it always shows */}
        {botTyping && (
          <div className="flex flex-col items-start px-4 pb-2">
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-[11px] font-medium text-gray-400">
                {chatInfo?.target_name}
              </span>
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-400">
              <span className="inline-flex gap-1">
                <span className="w-1.5 h-1.5 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1.5 h-1.5 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Input area */}
      {chatInfo && (
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
          {isSelf ? "我" : message.sender_name}
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
  if (msg.parts && msg.parts.length > 0) {
    const texts = msg.parts
      .filter((p) => p.type === "text" || p.type === "markdown")
      .map((p) => p.content ?? "");
    if (texts.length > 0) return texts.join("\n");
  }
  return msg.content || "";
}
