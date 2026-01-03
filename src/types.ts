export interface AIModel {
  id: string;
  name: string;
  provider: string;
  icon: string;
  description: string;
  category: string;
}

export type MessageContent = string | MessagePart[];

export type MessagePart = TextPart | FilePart;

export interface TextPart {
  type: 'text';
  text: string;
}

export interface FilePart {
  type: 'file';
  puter_path: string;
}

export interface Message {
  role: 'user' | 'assistant';
  content: MessageContent;
  attachments?: Attachment[];
  videoUrl?: string;
}

export interface Attachment {
  id: string;
  file?: File;
  name: string;
  size: number;
  type: string;
  previewUrl?: string;
  isImage: boolean;
  puterPath?: string;
  uploadProgress?: number;
  error?: string;
}

export interface AttachmentConfig {
  maxSize: number; // in bytes
  maxCount: number;
  allowedTypes: string[];
}

interface PuterResponse {
  message?: {
    content?: string | { text: string }[] | { text: string };
  } | string;
}

interface PuterFileHandle {
  path: string;
}

interface PuterFS {
  write: (path: string, file: File | Blob) => Promise<PuterFileHandle>;
  delete: (path: string) => Promise<void>;
}

interface PuterSDK {
  ai: {
    chat: (
      conversation: Message[],
      options: { model: string }
    ) => Promise<PuterResponse>;
    txt2vid: (
      prompt: string,
      options?: any
    ) => Promise<HTMLVideoElement>;
  };
  fs?: PuterFS;
}

interface MarkedOptions {
  breaks?: boolean;
  gfm?: boolean;
}

interface DOMPurifyConfig {
  ALLOWED_ATTR?: string[];
}

declare global {
  interface Window {
    puter?: PuterSDK;
    marked?: {
      parse: (text: string) => string;
      setOptions: (options: MarkedOptions) => void;
    };
    DOMPurify?: {
      sanitize: (html: string, options?: DOMPurifyConfig) => string;
    };
  }
}
