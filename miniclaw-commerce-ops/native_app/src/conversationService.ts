import { useAuthStore } from "@/stores/auth";
import { OperationsApiError, request } from "./operationsApiService";
import type {
  ConversationMessage,
  ConversationContextLink,
  ConversationContextRequest,
  ConversationStatus,
  ConversationSummary,
  ConversationThread,
} from "./operationsContracts";

interface ConversationSummaryDto {
  conversation_reference: string;
  title: string;
  status: ConversationStatus;
  status_label: string;
  latest_preview: string | null;
  created_at: string;
  updated_at: string;
  can_send: boolean;
}

interface ConversationMessageDto {
  message_reference: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  truncated: boolean;
  context: {
    kind: ConversationContextLink["kind"];
    reference: string;
    title: string;
    summary: string;
    return_path: string;
  } | null;
}

interface ConversationThreadDto extends ConversationSummaryDto {
  messages: ConversationMessageDto[];
  pending_submission: boolean;
  query_original_submission_only: boolean;
}

function mapSummary(dto: ConversationSummaryDto): ConversationSummary {
  return {
    conversationReference: dto.conversation_reference,
    title: dto.title,
    status: dto.status,
    statusLabel: dto.status_label,
    latestPreview: dto.latest_preview,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    canSend: dto.can_send,
  };
}

function mapMessage(dto: ConversationMessageDto): ConversationMessage {
  return {
    messageReference: dto.message_reference,
    role: dto.role,
    content: dto.content,
    timestamp: dto.timestamp,
    truncated: dto.truncated,
    context: dto.context ? {
      kind: dto.context.kind,
      reference: dto.context.reference,
      title: dto.context.title,
      summary: dto.context.summary,
      returnPath: dto.context.return_path,
    } : null,
  };
}

function mapThread(dto: ConversationThreadDto): ConversationThread {
  return {
    ...mapSummary(dto),
    messages: dto.messages.map(mapMessage),
    pendingSubmission: dto.pending_submission,
    queryOriginalSubmissionOnly: dto.query_original_submission_only,
  };
}

function userStoragePrefix(): string {
  const user = useAuthStore.getState().user;
  if (!user) throw new OperationsApiError("请重新登录后使用 Data Flow 对话。", 401);
  return `data-flow.conversation.${user.id}`;
}

function creationStorageKey(): string {
  return `${userStoragePrefix()}.creation`;
}

function submissionStorageKey(reference: string): string {
  return `${userStoragePrefix()}.submission.${reference}`;
}

export const conversationService = {
  async list(): Promise<ConversationSummary[]> {
    const dto = await request<{ conversations: ConversationSummaryDto[] }>("/conversations");
    return dto.conversations.map(mapSummary);
  },

  async get(reference: string): Promise<ConversationThread> {
    return mapThread(
      await request<ConversationThreadDto>(`/conversations/${encodeURIComponent(reference)}`),
    );
  },

  async create(title = "新对话"): Promise<ConversationThread> {
    const storageKey = creationStorageKey();
    const clientRequestId = window.sessionStorage.getItem(storageKey) ?? window.crypto.randomUUID();
    window.sessionStorage.setItem(storageKey, clientRequestId);
    try {
      const thread = mapThread(await request<ConversationThreadDto>("/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, client_request_id: clientRequestId }),
      }));
      if (thread.status !== "uncertain") window.sessionStorage.removeItem(storageKey);
      return thread;
    } catch (error) {
      if (error instanceof OperationsApiError && [401, 403, 409, 422].includes(error.status)) {
        window.sessionStorage.removeItem(storageKey);
      }
      throw error;
    }
  },

  hasPendingSubmission(reference: string): boolean {
    return Boolean(window.sessionStorage.getItem(submissionStorageKey(reference)));
  },

  async send(
    reference: string,
    content: string,
    context?: ConversationContextRequest,
  ): Promise<ConversationThread> {
    const storageKey = submissionStorageKey(reference);
    const idempotencyKey = window.sessionStorage.getItem(storageKey) ?? window.crypto.randomUUID();
    window.sessionStorage.setItem(storageKey, idempotencyKey);
    try {
      const thread = mapThread(await request<ConversationThreadDto>(
        `/conversations/${encodeURIComponent(reference)}/messages`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            content,
            idempotency_key: idempotencyKey,
            fee_confirmation: "confirmed",
            authorized_model_execution: true,
            context,
          }),
        },
      ));
      if (thread.status !== "uncertain") window.sessionStorage.removeItem(storageKey);
      return thread;
    } catch (error) {
      if (error instanceof OperationsApiError && [401, 403, 409, 422].includes(error.status)) {
        window.sessionStorage.removeItem(storageKey);
      }
      throw error;
    }
  },

  async recover(reference: string): Promise<ConversationThread> {
    const storageKey = submissionStorageKey(reference);
    const idempotencyKey = window.sessionStorage.getItem(storageKey);
    if (!idempotencyKey) {
      return this.get(reference);
    }
    const thread = mapThread(await request<ConversationThreadDto>(
      `/conversation-submissions/${encodeURIComponent(idempotencyKey)}`,
    ));
    if (thread.status !== "uncertain") window.sessionStorage.removeItem(storageKey);
    return thread;
  },
};
