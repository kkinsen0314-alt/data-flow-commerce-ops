import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  Bot,
  CheckCircle2,
  Clock3,
  LoaderCircle,
  MessageCircle,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  UserRound,
  X,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { conversationService } from "../conversationService";
import { WorkspaceDialog } from "../components/WorkspaceDialog";
import type {
  ConversationContextRequest,
  ConversationStatus,
  ConversationSummary,
  ConversationThread,
} from "../operationsContracts";

interface PendingContext {
  request: ConversationContextRequest;
  title: string;
  summary: string;
  returnPath: string;
}

const suggestions = [
  "请总结第 13 期最值得优先处理的经营问题。",
  "从内容、直播和成交链路给我一份本周行动清单。",
  "哪些指标最适合每天在数据看板里持续关注？",
];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Data Flow 对话请求失败，请稍后再试。";
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function statusClass(status: ConversationStatus): string {
  return status === "ready" ? "is-ready" : status === "processing" ? "is-processing" : "is-warning";
}

function contextFromSearch(params: URLSearchParams): PendingContext | null {
  if (params.get("context") === "task") {
    const reference = params.get("task_reference");
    if (reference && /^[A-F0-9]{12}$/.test(reference)) {
      return {
        request: { kind: "analysis_task", task_reference: reference },
        title: "分析任务",
        summary: `任务 #${reference}`,
        returnPath: `/operations/tasks/${reference}`,
      };
    }
  }
  if (params.get("context") === "visualization") {
    const filters = Object.fromEntries(
      ["source_id", "date_from", "date_to", "channel", "content", "session"]
        .map((key) => [key, params.get(key)] as const)
        .filter((entry): entry is readonly [string, string] => Boolean(entry[1])),
    );
    return {
      request: { kind: "visualization_view", visualization_filters: filters },
      title: "当前数据看板",
      summary: "使用当前筛选范围和经营指标",
      returnPath: `/operations/visualizations?${new URLSearchParams(filters).toString()}`,
    };
  }
  return null;
}

export default function ConversationsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedReference, setSelectedReference] = useState<string | null>(null);
  const [thread, setThread] = useState<ConversationThread | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loadingList, setLoadingList] = useState(true);
  const [loadingThread, setLoadingThread] = useState(false);
  const [creating, setCreating] = useState(false);
  const [sending, setSending] = useState(false);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [feeConfirmed, setFeeConfirmed] = useState(false);
  const [localUncertain, setLocalUncertain] = useState(false);
  const [pendingContext, setPendingContext] = useState<PendingContext | null>(
    () => contextFromSearch(searchParams),
  );
  const messageList = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const linked = contextFromSearch(searchParams);
    if (linked) setPendingContext(linked);
  }, [searchParams]);

  const clearPendingContext = () => {
    setPendingContext(null);
    setSearchParams({}, { replace: true });
  };

  const refreshList = async (preferredReference?: string) => {
    const items = await conversationService.list();
    setConversations(items);
    setSelectedReference((current) => {
      const preferred = preferredReference ?? current;
      if (preferred && items.some((item) => item.conversationReference === preferred)) return preferred;
      return items[0]?.conversationReference ?? null;
    });
  };

  useEffect(() => {
    let active = true;
    setLoadingList(true);
    conversationService.list()
      .then((items) => {
        if (!active) return;
        setConversations(items);
        setSelectedReference(items[0]?.conversationReference ?? null);
        setError("");
      })
      .catch((error: unknown) => active && setError(errorMessage(error)))
      .finally(() => active && setLoadingList(false));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!selectedReference) {
      setThread(null);
      return;
    }
    let active = true;
    const load = async () => {
      setLoadingThread(true);
      try {
        const next = await conversationService.get(selectedReference);
        if (!active) return;
        setThread(next);
        setLocalUncertain(
          next.status === "uncertain" || conversationService.hasPendingSubmission(selectedReference),
        );
        setError("");
      } catch (error) {
        if (active) setError(errorMessage(error));
      } finally {
        if (active) setLoadingThread(false);
      }
    };
    void load();
    return () => { active = false; };
  }, [selectedReference]);

  useEffect(() => {
    if (!selectedReference || thread?.status !== "processing") return;
    let active = true;
    let polling = false;
    const timer = setInterval(async () => {
      if (polling) return;
      polling = true;
      try {
        const next = await conversationService.get(selectedReference);
        if (!active) return;
        setThread(next);
        if (next.status !== "processing") await refreshList(next.conversationReference);
      } catch (error) {
        if (active) setError(errorMessage(error));
      } finally {
        polling = false;
      }
    }, 2500);
    return () => { active = false; clearInterval(timer); };
  }, [selectedReference, thread?.status]);

  useEffect(() => {
    const list = messageList.current;
    if (list) list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
  }, [thread?.messages.length, thread?.status]);

  const createConversation = async () => {
    setCreating(true);
    setError("");
    try {
      const next = await conversationService.create();
      setThread(next);
      setSelectedReference(next.conversationReference);
      await refreshList(next.conversationReference);
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setCreating(false);
    }
  };

  const openConfirmation = (event: FormEvent) => {
    event.preventDefault();
    if (!thread?.canSend || !message.trim() || sending) return;
    setFeeConfirmed(false);
    setShowConfirmation(true);
  };

  const sendMessage = async () => {
    if (!thread || !message.trim() || !feeConfirmed) return;
    const outgoing = message.trim();
    setSending(true);
    setError("");
    try {
      const next = await conversationService.send(
        thread.conversationReference,
        outgoing,
        pendingContext?.request,
      );
      setThread(next);
      setLocalUncertain(next.status === "uncertain");
      if (next.status !== "uncertain") {
        setMessage("");
        clearPendingContext();
      }
      setShowConfirmation(false);
      await refreshList(next.conversationReference);
    } catch (error) {
      setLocalUncertain(conversationService.hasPendingSubmission(thread.conversationReference));
      setShowConfirmation(false);
      setError(errorMessage(error));
    } finally {
      setSending(false);
    }
  };

  const queryOriginalSubmission = async () => {
    if (!thread) return;
    setLoadingThread(true);
    setError("");
    try {
      const next = await conversationService.recover(thread.conversationReference);
      setThread(next);
      setLocalUncertain(next.status === "uncertain");
      if (next.status !== "uncertain") {
        setMessage("");
        clearPendingContext();
      }
      await refreshList(next.conversationReference);
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setLoadingThread(false);
    }
  };

  return (
    <>
      <header className="df-workspace-header df-chat-page-header">
        <div>
          <p className="df-eyebrow">智能协作</p>
          <h1>运营对话</h1>
          <p className="df-page-description">直接向 Data Flow 提问，围绕经营数据、分析任务和行动方案持续协作。</p>
        </div>
        <button className="df-primary-button" type="button" onClick={createConversation} disabled={creating}>
          {creating ? <LoaderCircle className="df-spin" size={17} /> : <Plus size={17} />}
          {creating ? "正在创建" : "新建对话"}
        </button>
      </header>

      {error && <div className="df-chat-alert" role="alert"><ShieldCheck size={17} /><span>{error}</span></div>}

      <section className="df-chat-workspace">
        <aside className="df-conversation-sidebar">
          <div className="df-conversation-sidebar-head">
            <div><p className="df-eyebrow">会话记录</p><strong>{conversations.length} 个对话</strong></div>
            <button type="button" aria-label="刷新会话" onClick={() => void refreshList()} disabled={loadingList}>
              <RefreshCw className={loadingList ? "df-spin" : ""} size={16} />
            </button>
          </div>
          <div className="df-conversation-list">
            {loadingList && conversations.length === 0 ? (
              <div className="df-conversation-list-state"><LoaderCircle className="df-spin" size={20} />读取会话</div>
            ) : conversations.length === 0 ? (
              <div className="df-conversation-list-state"><MessageCircle size={20} />还没有对话</div>
            ) : conversations.map((item) => (
              <button
                type="button"
                className={item.conversationReference === selectedReference ? "is-active" : ""}
                onClick={() => setSelectedReference(item.conversationReference)}
                key={item.conversationReference}
              >
                <div><strong>{item.title}</strong><span>{item.latestPreview ?? item.statusLabel}</span></div>
                <small><Clock3 size={12} />{formatTime(item.updatedAt)}</small>
              </button>
            ))}
          </div>
        </aside>

        <section className="df-chat-panel" aria-label="对话内容">
          {!selectedReference ? (
            <div className="df-chat-welcome">
              <div className="df-chat-welcome-mark"><Sparkles size={26} /></div>
              <p className="df-eyebrow">Data Flow</p>
              <h2>从一个运营问题开始</h2>
              <p>新建对话后，可以连续追问数据表现、原因判断和下一步行动。</p>
              <button className="df-primary-button" type="button" onClick={createConversation} disabled={creating}><Plus size={17} />新建对话</button>
            </div>
          ) : loadingThread && !thread ? (
            <div className="df-chat-welcome"><LoaderCircle className="df-spin" size={28} /><p>正在读取对话内容</p></div>
          ) : thread ? (
            <>
              <div className="df-chat-thread-head">
                <div><h2>{thread.title}</h2><span>#{thread.conversationReference}</span></div>
                <span className={`df-chat-status ${statusClass(thread.status)}`}>
                  {thread.status === "processing" ? <LoaderCircle className="df-spin" size={13} /> : <CheckCircle2 size={13} />}
                  {thread.statusLabel}
                </span>
              </div>

              <div className="df-chat-messages" ref={messageList} aria-live="polite">
                {thread.messages.length === 0 ? (
                  <div className="df-chat-empty">
                    <Bot size={25} />
                    <h3>你想先了解什么？</h3>
                    <p>可以从以下问题开始，也可以直接输入自己的运营问题。</p>
                    <div>{suggestions.map((suggestion) => <button type="button" key={suggestion} onClick={() => setMessage(suggestion)}>{suggestion}</button>)}</div>
                  </div>
                ) : thread.messages.map((item) => (
                  <article className={`df-chat-message is-${item.role}`} key={item.messageReference}>
                    <div className="df-chat-avatar">{item.role === "assistant" ? <Bot size={17} /> : <UserRound size={17} />}</div>
                    <div className="df-chat-bubble">
                      <div><strong>{item.role === "assistant" ? "Data Flow" : "你"}</strong><time>{formatTime(item.timestamp)}</time></div>
                      {item.context && <Link className="df-chat-context-link" to={item.context.returnPath}><Sparkles size={13} /><span><strong>{item.context.title}</strong><small>{item.context.summary}</small></span></Link>}
                      <p>{item.content}</p>
                      {item.truncated && <small>内容较长，当前仅展示前 20,000 个字符。</small>}
                    </div>
                  </article>
                ))}
                {thread.status === "processing" && <div className="df-chat-thinking" role="status"><LoaderCircle className="df-spin" size={16} /><span>Data Flow 正在整理回复</span></div>}
                {(thread.queryOriginalSubmissionOnly || localUncertain) && (
                  <div className="df-chat-recovery" role="status">
                    <ShieldCheck size={18} />
                    <div><strong>原消息发送状态待确认</strong><p>系统不会自动重新发送，也不会创建新的调用。请查询这一次发送的状态。</p></div>
                    <button className="df-secondary-button" type="button" onClick={queryOriginalSubmission} disabled={loadingThread}>{loadingThread ? <LoaderCircle className="df-spin" size={15} /> : <RefreshCw size={15} />}查询原发送</button>
                  </div>
                )}
              </div>

              <form className="df-chat-composer" onSubmit={openConfirmation}>
                {pendingContext && <div className="df-chat-context-pending">
                  <Sparkles size={16} />
                  <Link to={pendingContext.returnPath}><strong>{pendingContext.title}</strong><span>{pendingContext.summary}</span></Link>
                  <button type="button" aria-label="移除关联上下文" onClick={clearPendingContext} disabled={sending}><X size={15} /></button>
                </div>}
                <textarea
                  aria-label="运营问题"
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  placeholder={thread.canSend ? "输入你的运营问题，Enter 换行" : "当前消息处理完成后可继续提问"}
                  rows={3}
                  maxLength={6000}
                  disabled={!thread.canSend || sending || localUncertain}
                />
                <div>
                  <span>{message.length} / 6000</span>
                  <button className="df-primary-button" type="submit" disabled={!thread.canSend || !message.trim() || sending || localUncertain}><Send size={16} />发送</button>
                </div>
                <p><ShieldCheck size={13} />每次发送前都会确认模型调用；系统不会自动重发消息。</p>
              </form>
            </>
          ) : null}
        </section>
      </section>

      <WorkspaceDialog open={showConfirmation && Boolean(thread)} onClose={() => setShowConfirmation(false)} busy={sending} titleId="chat-confirm-title" className="df-confirm-dialog">
          <button className="df-icon-button df-dialog-close" type="button" aria-label="关闭" onClick={() => setShowConfirmation(false)} disabled={sending}><X size={19} /></button>
          <div className="df-dialog-mark"><MessageCircle size={24} /></div>
          <p className="df-eyebrow">发送确认</p>
          <h2 id="chat-confirm-title">向 Data Flow 发送这条消息</h2>
          <p className="df-chat-confirm-preview">{message.trim()}</p>
          <label className="df-dialog-note"><input type="checkbox" checked={feeConfirmed} onChange={(event) => setFeeConfirmed(event.target.checked)} disabled={sending} /> 我确认调用已配置的模型，并知晓本次回复可能产生费用。</label>
          <div className="df-dialog-actions"><button className="df-secondary-button" type="button" onClick={() => setShowConfirmation(false)} disabled={sending}>返回修改</button><button className="df-primary-button" type="button" onClick={sendMessage} disabled={sending || !feeConfirmed}>{sending ? <LoaderCircle className="df-spin" size={17} /> : <Send size={17} />}{sending ? "正在发送" : "确认发送"}</button></div>
      </WorkspaceDialog>
    </>
  );
}
