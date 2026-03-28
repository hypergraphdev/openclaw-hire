import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { ChatInfo, ChatMessage } from "../types";

const EMOJI_LIST = ["😀","😂","🤣","😊","😍","🥰","😘","😎","🤔","😅","😢","😭","😤","🔥","❤️","👍","👎","👋","🎉","🙏","💯","✨","⭐","🚀","💡","📎","✅","❌","⚡","🌟"];

function EmojiPicker({ onSelect, onClose }: { onSelect: (e: string) => void; onClose: () => void }) {
  return (
    <div className="absolute bottom-12 left-0 bg-gray-800 border border-gray-700 rounded-lg p-3 shadow-xl z-50 w-[340px]">
      <div className="grid grid-cols-10 gap-1">
        {EMOJI_LIST.map((e) => (
          <button key={e} onClick={() => { onSelect(e); onClose(); }}
            className="w-8 h-8 flex items-center justify-center text-lg hover:bg-gray-700 rounded">{e}</button>
        ))}
      </div>
    </div>
  );
}

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
  const [input, setInputRaw] = useState(() => localStorage.getItem(`chat_draft_${instanceId}`) || "");
  const setInput = useCallback((v: string | ((p: string) => string)) => {
    setInputRaw((prev) => {
      const next = typeof v === "function" ? v(prev) : v;
      if (next) localStorage.setItem(`chat_draft_${instanceId}`, next); else localStorage.removeItem(`chat_draft_${instanceId}`);
      return next;
    });
  }, [instanceId]);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const [wsStatus, setWsStatus] = useState<"connecting" | "connected" | "disconnected">("disconnected");
  const [botTyping, setBotTyping] = useState(false);
  const [pendingImage, setPendingImage] = useState<{ file: File; preview: string } | null>(null);
  const [showEmoji, setShowEmoji] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Refs
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const generalFileRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const userScrolledUp = useRef(false);
  const adminBotIdRef = useRef("");

  // ─── Load chat info (target bot + admin bot identity) ───────────

  useEffect(() => {
    setInfoLoading(true);
    setInfoError("");
    api.chatInfo(instanceId)
      .then((info) => {
        setChatInfo(info);
        adminBotIdRef.current = info.admin_bot_id || "";
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
              const raw = data.message;
              // Normalize content fields from Hub (may be objects)
              if (raw.content && typeof raw.content !== "string") {
                raw.content = typeof raw.content === "object" && raw.content.text ? raw.content.text : JSON.stringify(raw.content);
              }
              if (raw.parts) {
                for (const p of raw.parts) {
                  if (p.content && typeof p.content !== "string") {
                    p.content = typeof p.content === "object" && p.content.text ? p.content.text : JSON.stringify(p.content);
                  }
                }
              }
              const msg: ChatMessage = raw;
              // Only stop typing when the BOT replies (not our own echo)
              if (msg.sender_id !== adminBotIdRef.current) {
                setBotTyping(false);
                clearTimeout(typingTimer.current);
              }
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

  function handlePickImage() {
    fileInputRef.current?.click();
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setSendError("只支持图片文件");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setSendError("图片大小不能超过 10MB");
      return;
    }
    setSendError("");
    const preview = URL.createObjectURL(file);
    setPendingImage({ file, preview });
    // Reset input so re-selecting same file triggers change
    e.target.value = "";
  }

  function cancelImage() {
    if (pendingImage) {
      URL.revokeObjectURL(pendingImage.preview);
      setPendingImage(null);
    }
  }

  async function handleSend() {
    if (!chatInfo || sending) return;
    if (!input.trim() && !pendingImage) return;
    setSending(true);
    setSendError("");
    // Start typing indicator immediately after sending
    setBotTyping(true);
    clearTimeout(typingTimer.current);
    typingTimer.current = setTimeout(() => setBotTyping(false), 30000);
    try {
      let imageUrl: string | undefined;
      // Upload image first if present
      if (pendingImage) {
        setUploading(true);
        const uploaded = await api.chatUpload(instanceId, pendingImage.file);
        imageUrl = uploaded.url;
        URL.revokeObjectURL(pendingImage.preview);
        setPendingImage(null);
        setUploading(false);
      }
      const res = await api.chatSend(instanceId, input.trim(), imageUrl);
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
      setUploading(false);
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
                instanceId={instanceId}
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
          {/* Image preview */}
          {pendingImage && (
            <div className="mb-2 relative inline-block">
              <img
                src={pendingImage.preview}
                alt="preview"
                className="max-h-32 rounded-lg border border-gray-700"
              />
              <button
                onClick={cancelImage}
                className="absolute -top-2 -right-2 w-5 h-5 bg-red-600 text-white rounded-full text-xs flex items-center justify-center hover:bg-red-500"
              >
                &times;
              </button>
            </div>
          )}
          <div className="flex gap-2 items-center">
            {/* Hidden file input */}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={handleFileChange}
            />
            {/* Hidden general file input */}
            <input
              ref={generalFileRef}
              type="file"
              accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.csv,.zip,.tar,.gz,.json,.xml,.mp3,.mp4,.wav,.jpg,.jpeg,.png,.gif,.webp"
              className="hidden"
              onChange={async (e) => {
                const f = e.target.files?.[0]; if (!f) return; e.target.value = "";
                try {
                  setUploading(true);
                  const result = await api.myOrgFileUpload(f);
                  const link = `\u{1F4CE} [${result.filename}](${result.url}) (${result.size_kb}KB)`;
                  setInput((v) => v ? v + "\n" + link : link);
                } catch (err: unknown) { setSendError((err as Error).message || "上传失败"); }
                finally { setUploading(false); }
              }}
            />
            {/* Image picker button */}
            <button
              onClick={handlePickImage}
              disabled={sending || !!pendingImage}
              className="shrink-0 p-2 text-gray-400 hover:text-gray-200 disabled:opacity-40 transition-colors"
              title="发送图片"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0 0 22.5 18.75V5.25A2.25 2.25 0 0 0 20.25 3H3.75A2.25 2.25 0 0 0 1.5 5.25v13.5A2.25 2.25 0 0 0 3.75 21Zm16.5-13.5a1.125 1.125 0 1 1-2.25 0 1.125 1.125 0 0 1 2.25 0Z" />
              </svg>
            </button>
            {/* File upload button */}
            <button
              onClick={() => generalFileRef.current?.click()}
              disabled={sending || uploading}
              className="shrink-0 p-2 text-gray-400 hover:text-gray-200 disabled:opacity-40 transition-colors"
              title="上传文件"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941l-7.81 7.81a1.5 1.5 0 002.112 2.13" />
              </svg>
            </button>
            {/* Emoji picker */}
            <div className="relative">
              <button onClick={() => setShowEmoji(!showEmoji)} className="shrink-0 p-2 text-gray-400 hover:text-gray-200" title="Emoji">😀</button>
              {showEmoji && <EmojiPicker onSelect={(e) => setInput((v) => v + e)} onClose={() => setShowEmoji(false)} />}
            </div>
            <textarea
              className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 outline-none focus:border-blue-500 placeholder-gray-500 resize-none overflow-y-auto"
              placeholder={pendingImage ? "添加图片说明..." : t("chat.inputPlaceholder")}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
              onInput={(e) => { const el = e.currentTarget; el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 120) + "px"; }}
              rows={1}
              style={{ maxHeight: 120 }}
              disabled={sending}
            />
            <button
              onClick={handleSend}
              disabled={(!input.trim() && !pendingImage) || sending}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded-lg transition-colors"
            >
              {uploading ? "上传中..." : sending ? t("chat.sending") : t("chat.send")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── File Path Links ────────────────────────────────────────────────

const FILE_PATH_ROOTS: Record<string, string> = {
  "/home/node/.openclaw/workspace/": "/",
  "/home/zylos/zylos/": "/",
};

function RenderTextWithFileLinks({ text, instanceId }: { text: string; instanceId: string }) {
  // Match container file paths and make them downloadable
  const regex = /(?:`)?(\/(home\/node\/\.openclaw\/workspace|home\/zylos\/zylos)\/[^\s`'",)]+)(?:`)?/g;
  const parts: (string | { path: string; display: string })[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const fullPath = m[1];
    // Convert container path to relative path for download API
    let relPath = fullPath;
    for (const [prefix, root] of Object.entries(FILE_PATH_ROOTS)) {
      if (fullPath.startsWith(prefix)) {
        relPath = root + fullPath.slice(prefix.length);
        break;
      }
    }
    parts.push({ path: relPath, display: fullPath });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  if (parts.length === 1 && typeof parts[0] === "string") return <span>{text}</span>;

  return (
    <span>
      {parts.map((p, i) =>
        typeof p === "string" ? (
          <span key={i}>{p}</span>
        ) : (
          <a
            key={i}
            className="text-blue-400 hover:text-blue-300 underline cursor-pointer"
            onClick={(e) => {
              e.preventDefault();
              const token = localStorage.getItem("token") || "";
              const base = import.meta.env.VITE_API_BASE || "";
              fetch(`${base}/api/instances/${instanceId}/files/download?path=${encodeURIComponent(p.path)}`, {
                headers: { Authorization: `Bearer ${token}` },
              })
                .then((r) => { if (!r.ok) throw new Error("Download failed"); return r.blob(); })
                .then((blob) => {
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = p.path.split("/").pop() || "file";
                  a.click();
                  URL.revokeObjectURL(url);
                })
                .catch(() => alert("Download failed"));
            }}
          >
            {p.display}
          </a>
        ),
      )}
    </span>
  );
}

// ─── Message Bubble ─────────────────────────────────────────────────

function MessageBubble({ message, isSelf, instanceId }: { message: ChatMessage; isSelf: boolean; instanceId: string }) {
  const time = new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const content = extractContent(message);
  const { imageUrl, text } = parseImageContent(content);

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
        {imageUrl && (
          <img
            src={imageUrl}
            alt="图片"
            className="max-w-full max-h-64 rounded mb-1 cursor-pointer"
            onClick={() => window.open(imageUrl, "_blank")}
          />
        )}
        {text && <RenderTextWithFileLinks text={text} instanceId={instanceId} />}
      </div>
    </div>
  );
}

/** Parse image markdown from message content: [图片](url) */
function parseImageContent(content: string): { imageUrl: string | null; text: string } {
  const match = content.match(/^\[图片\]\((https?:\/\/[^\s)]+)\)\s*/);
  if (match) {
    return { imageUrl: match[1], text: content.slice(match[0].length).trim() };
  }
  return { imageUrl: null, text: content };
}

/** Extract displayable content from a message. */
function safeStr(v: unknown): string {
  if (typeof v === "string") return v;
  if (v == null) return "";
  if (typeof v === "object") {
    // Hub may send content as {text: "..."} object
    const obj = v as Record<string, unknown>;
    if (typeof obj.text === "string") return obj.text;
    try { return JSON.stringify(v); } catch { return ""; }
  }
  return String(v);
}

function extractContent(msg: ChatMessage): string {
  if (msg.parts && msg.parts.length > 0) {
    const texts = msg.parts
      .filter((p) => p.type === "text" || p.type === "markdown")
      .map((p) => safeStr(p.content));
    if (texts.length > 0) return texts.join("\n");
  }
  return safeStr(msg.content) || "";
}
