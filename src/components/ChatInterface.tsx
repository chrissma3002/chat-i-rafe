import { useState, useEffect, useRef, useCallback } from 'react';
import { ArrowLeft, Send, Loader2, Paperclip, X } from 'lucide-react';
import {
  AIModel,
  Message,
  Attachment,
  AttachmentConfig,
  MessageContent,
  MessagePart,
} from '../types';

const hasFiles = (dataTransfer?: DataTransfer | null) =>
  !!dataTransfer?.types?.includes('Files');

const filesFromDataTransfer = (dataTransfer: DataTransfer | null): File[] => {
  if (!dataTransfer) return [];
  if (dataTransfer.files?.length) {
    return Array.from(dataTransfer.files);
  }
  if (dataTransfer.items?.length) {
    return Array.from(dataTransfer.items)
      .filter((item) => item.kind === 'file')
      .map((item) => item.getAsFile())
      .filter((file): file is File => Boolean(file));
  }
  return [];
};

const isTextPart = (part: MessagePart): part is Extract<MessagePart, { type: 'text' }> =>
  part.type === 'text';

const extractTextFromContent = (content: MessageContent): string => {
  if (typeof content === 'string') return content;
  return content
    .filter(isTextPart)
    .map((part) => part.text)
    .join('\n')
    .trim();
};

const getMessageText = (content: MessageContent): string =>
  typeof content === 'string' ? content : extractTextFromContent(content);

const extractResponseText = (payload: any): string => {
  if (!payload) return '';
  if (typeof payload === 'string') return payload;
  if (typeof payload?.text === 'string') return payload.text;

  const message = payload.message ?? payload;

  if (typeof message === 'string') return message;
  if (typeof message?.content === 'string') return message.content;

  if (Array.isArray(message?.content)) {
    return message.content
      .map((item: any) => {
        if (!item) return '';
        if (typeof item === 'string') return item;
        if (typeof item.text === 'string') return item.text;
        return '';
      })
      .join('');
  }

  if (
    typeof message?.content === 'object' &&
    message?.content !== null &&
    'text' in message.content
  ) {
    return (message.content as { text?: string }).text ?? '';
  }

  return '';
};

const isAsyncIterable = (value: unknown): value is AsyncIterable<unknown> =>
  Boolean(value && typeof (value as any)[Symbol.asyncIterator] === 'function');

const generateTempFilename = (originalName: string) => {
  const extensionMatch = originalName?.match(/(\.[a-zA-Z0-9]+)$/);
  const extension = extensionMatch ? extensionMatch[1] : '';
  return `claude_upload_${Date.now()}_${Math.random().toString(36).slice(2, 8)}${extension}`;
};

interface ChatInterfaceProps {
  model: AIModel;
  onBack: () => void;
}

type StatusType = 'ready' | 'thinking' | 'error';

export default function ChatInterface({ model, onBack }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [status, setStatus] = useState<StatusType>('ready');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const conversationRef = useRef<Message[]>([]);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const [copiedResponseIndex, setCopiedResponseIndex] = useState<number | null>(null);
  const [expandedMessages, setExpandedMessages] = useState<Set<number>>(new Set());
  const [animatingMessages, setAnimatingMessages] = useState<Set<number>>(new Set());
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [dragCounter, setDragCounter] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sessionFilesRef = useRef<Set<string>>(new Set());
  const [statusMessage, setStatusMessage] = useState('Ready');
  const streamingMessageIndexRef = useRef<number | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      const newHeight = Math.min(textareaRef.current.scrollHeight, 200);
      textareaRef.current.style.height = `${newHeight}px`;
    }
  }, [input]);

  const renderMarkdown = (text: string): string => {
    if (window.marked && window.DOMPurify) {
      window.marked.setOptions({ breaks: true, gfm: true });

      const renderer = new window.marked.Renderer();
      renderer.code = (code: string, language: string, escaped?: boolean) => {
        const validLanguage = language ? `language-${language}` : '';
        const escapeHtml = (unsafe: string) => {
          return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
        };
        const finalCode = escaped ? code : escapeHtml(code);

        return `
<div class="code-block-wrapper relative group">
<div class="sticky top-0 z-10 flex justify-end px-2 pt-2 h-0 overflow-visible pointer-events-none">
<button class="code-copy-btn pointer-events-auto" type="button">
<span class="copy-label">Copy</span>
</button>
</div>
<pre><code class="${validLanguage}">${finalCode}</code></pre>
</div>`;
      };

      const html = window.marked.parse(text, { renderer });
      return window.DOMPurify.sanitize(html, {
        ALLOWED_ATTR: ['href', 'title', 'target', 'class'],
      });
    }
    return text.replace(/\n/g, '<br>');
  };

  const copyToClipboard = useCallback(async (text: string) => {
    if (!text) return false;
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (err) {
        console.error('Clipboard copy failed:', err);
      }
    }

    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      return true;
    } catch (err) {
      console.error('Fallback copy failed:', err);
      return false;
    }
  }, []);

  const handleCopyResponse = useCallback(
    async (content: MessageContent, index: number) => {
      const text =
        typeof content === 'string' ? content : extractTextFromContent(content);
      const success = await copyToClipboard(text);
      if (success) {
        setCopiedResponseIndex(index);
        setTimeout(() => {
          setCopiedResponseIndex((prev) => (prev === index ? null : prev));
        }, 1800);
      }
    },
    [copyToClipboard]
  );

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    const handleClick = async (event: Event) => {
      const target = event.target as HTMLElement;
      const button = target.closest('.code-copy-btn') as HTMLButtonElement | null;
      if (!button) return;

      const wrapper = button.closest('.code-block-wrapper');
      const pre = wrapper ? wrapper.querySelector('pre') : button.closest('pre');

      const codeElement = pre?.querySelector('code');
      const codeText = codeElement ? codeElement.textContent : (pre?.textContent ?? '');

      if (!codeText) return;

      const success = await copyToClipboard(codeText.trim());

      if (success) {
        button.dataset.copied = 'true';
        const label = button.querySelector('.copy-label');
        if (label) {
          label.textContent = 'Copied';
        }
        setTimeout(() => {
          button.dataset.copied = 'false';
          if (label) label.textContent = 'Copy';
        }, 1500);
      }
    };

    container.addEventListener('click', handleClick);
    return () => {
      container.removeEventListener('click', handleClick);
    };
  }, [copyToClipboard]);

  const toggleExpandMessage = useCallback((index: number) => {
    setAnimatingMessages((prev) => {
      const newSet = new Set(prev);
      newSet.add(index);
      return newSet;
    });

    setTimeout(() => {
      setExpandedMessages((prev) => {
        const newSet = new Set(prev);
        if (newSet.has(index)) {
          newSet.delete(index);
        } else {
          newSet.add(index);
        }
        return newSet;
      });

      setTimeout(() => {
        setAnimatingMessages((prev) => {
          const newSet = new Set(prev);
          newSet.delete(index);
          return newSet;
        });
      }, 400);
    }, 50);
  }, []);

  const attachmentConfig: AttachmentConfig = {
    maxSize: 10 * 1024 * 1024, // 10MB
    maxCount: 5,
    allowedTypes: [
      'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml',
      'application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'text/plain', 'text/markdown'
    ]
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const createAttachment = useCallback((file: File): Attachment => {
    const id =
      window.crypto?.randomUUID?.() ?? `att-${Date.now()}-${Math.random()}`;
    const isImage = file.type?.startsWith('image/');
    const previewUrl = isImage ? URL.createObjectURL(file) : undefined;

    return {
      id,
      file,
      name: file.name,
      size: file.size,
      type: file.type || '',
      previewUrl,
      isImage,
      uploadProgress: 0,
    };
  }, []);

  const validateFile = useCallback(
    (file: File, currentCount: number): string | null => {
      if (!attachmentConfig.allowedTypes.includes(file.type)) {
        return `File type ${file.type || 'unknown'} is not supported`;
      }
      if (file.size > attachmentConfig.maxSize) {
        return `File size exceeds ${formatFileSize(attachmentConfig.maxSize)} limit`;
      }
      if (currentCount >= attachmentConfig.maxCount) {
        return `Maximum ${attachmentConfig.maxCount} files allowed`;
      }
      return null;
    },
    [attachmentConfig]
  );

  const addAttachments = useCallback(
    (files: FileList | File[]) => {
      const fileArray = Array.from(files || []);
      if (!fileArray.length) return;

      setAttachments((current) => {
        const additions: Attachment[] = [];
        const errors: string[] = [];
        let runningCount = current.length;

        for (const file of fileArray) {
          const error = validateFile(file, runningCount);
          if (error) {
            errors.push(`${file.name}: ${error}`);
            continue;
          }

          additions.push(createAttachment(file));
          runningCount += 1;
        }

        if (errors.length) {
          console.error('Attachment errors:', errors);
        }

        if (!additions.length) {
          return current;
        }

        return [...current, ...additions];
      });
    },
    [createAttachment, validateFile]
  );

  const removeAttachment = (id: string) => {
    setAttachments((prev) => {
      const target = prev.find((att) => att.id === id);
      if (target?.previewUrl) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return prev.filter(att => att.id !== id);
    });
  };

  const clearAttachments = () => {
    setAttachments([]);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const uploadAttachments = useCallback(
    async (files: Attachment[]): Promise<Attachment[]> => {
      if (!window.puter?.fs) {
        throw new Error('File uploads are not supported in this environment.');
      }

      const uploaded: Attachment[] = [];
      for (const attachment of files) {
        if (!attachment.file) continue;
        const tempName = generateTempFilename(attachment.name);
        const handle = await window.puter.fs.write(tempName, attachment.file);
        sessionFilesRef.current.add(handle.path);
        uploaded.push({
          ...attachment,
          file: undefined,
          puterPath: handle.path,
        });
      }
      return uploaded;
    },
    []
  );

  const buildUserMessageContent = (text: string, uploaded: Attachment[]): MessageContent => {
    if (!uploaded.length) {
      return text;
    }

    const parts: MessagePart[] = uploaded
      .filter((att): att is Attachment & { puterPath: string } => Boolean(att.puterPath))
      .map((att) => ({
        type: 'file',
        puter_path: att.puterPath!,
      }));

    if (text) {
      parts.push({ type: 'text', text });
    }

    return parts;
  };

  const cleanupSessionFiles = useCallback(async () => {
    if (!window.puter?.fs) return;
    const deletions = Array.from(sessionFilesRef.current).map(async (path) => {
      try {
        await window.puter!.fs!.delete(path);
      } catch (error) {
        console.warn('Failed to delete temp file:', error);
      }
    });
    await Promise.allSettled(deletions);
    sessionFilesRef.current.clear();
  }, []);

  const handleDragEnter = (e: React.DragEvent) => {
    if (!hasFiles(e.dataTransfer)) return;
    e.preventDefault();
    e.stopPropagation();
    setDragCounter(prev => prev + 1);
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    if (!hasFiles(e.dataTransfer)) return;
    e.preventDefault();
    e.stopPropagation();
    setDragCounter(prev => Math.max(0, prev - 1));
    if (dragCounter <= 1) {
      setIsDragging(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    if (!hasFiles(e.dataTransfer)) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleDrop = (e: React.DragEvent) => {
    if (!hasFiles(e.dataTransfer)) return;
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    setDragCounter(0);

    const files = filesFromDataTransfer(e.dataTransfer);
    if (files.length > 0) {
      addAttachments(files);
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const files = filesFromDataTransfer(e.clipboardData);
    if (files.length > 0) {
      e.preventDefault();
      addAttachments(files);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      addAttachments(files);
    }
    // Reset input value to allow selecting the same file again
    e.target.value = '';
  };

  const triggerFileSelect = () => {
    fileInputRef.current?.click();
  };

  const sanitizeAttachments = (items: Attachment[]): Attachment[] =>
    items.map(({ id, name, size, type, previewUrl, isImage, puterPath }) => ({
      id,
      name,
      size,
      type,
      previewUrl,
      isImage,
      puterPath,
    }));

  const sendMessage = async () => {
    if ((status === 'thinking') || (!input.trim() && attachments.length === 0)) return;

    // 1. Capture current state
    const textToSend = input.trim();
    const attachmentsToSend = [...attachments];

    // 2. Clear UI immediately
    setInput('');
    clearAttachments();
    setStatus('thinking');

    // 3. Update UI message list (optimistic update with local logic)
    // We keep the local attachments for display purposes
    const displayAttachments = sanitizeAttachments(attachmentsToSend);
    const userMessageDisplay: Message = {
      role: 'user',
      content: textToSend || (displayAttachments.length ? '[Attachment]' : ''),
      attachments: displayAttachments,
    };

    const newMessages = [...messages, userMessageDisplay];
    setMessages(newMessages);

    // Update conversation ref with the display message first (will be updated with paths later if needed, 
    // but actually we should probably store the version WITH paths in the conversationRef for the API).
    // Let's store the display version first to maintain order? 
    // No, conversationRef is for the API. We can just append to it later.
    // However, if we want to stream or something, we might need it.
    // Let's wait for upload to append to conversationRef to be safe with the paths.

    try {
      if (!window.puter) {
        throw new Error('Puter SDK not loaded');
      }

      // HANDLE VIDEO GENERATION
      if (model.id === 'video-generation') {
        const videoPrompt = textToSend || (attachmentsToSend[0]?.name ? `Video based on ${attachmentsToSend[0].name}` : "Generate a video");

        // Setup options, handling optional image reference
        let options: any = {
          test_mode: true // Enable test mode to avoid credit usage during development
        };
        if (attachmentsToSend.length > 0 && attachmentsToSend[0].file) {
          options.input_reference = attachmentsToSend[0].file;
        }

        const videoElement = await window.puter.ai.txt2vid(videoPrompt, options);
        // The returned element has a src blob
        const videoUrl = videoElement.src;

        const assistantMessage: Message = {
          role: 'assistant',
          content: 'Here is your generated video:',
          videoUrl: videoUrl
        };

        conversationRef.current = [...conversationRef.current, assistantMessage];
        setMessages((prev) => [...prev, assistantMessage]);
        setStatus('ready');
        return;
      }

      // 4. Upload files
      let uploadedFiles: Attachment[] = [];
      if (attachmentsToSend.length > 0) {
        // Update status if you want, but 'thinking' is fine. 
        // Example: setStatus('uploading'); but the type only has 'ready' | 'thinking' | 'error'
        uploadedFiles = await uploadAttachments(attachmentsToSend);
      }

      // 5. Build conversation message with Puter paths
      const apiContent = buildUserMessageContent(textToSend, uploadedFiles);

      const userMessageForApi: Message = {
        role: 'user',
        content: apiContent,
        // We don't send 'attachments' field to the API, it expects content array.
      };

      // Update conversation history for the AI context
      conversationRef.current = [...conversationRef.current, userMessageForApi];

      // 6. Call AI API with streaming (and enable web search for Grok)
      const chatOptions: any = {
        model: model.id,
        stream: true,
      };

      if (model.id === 'x-ai/grok-4.1-fast' || model.id.startsWith('grok-')) {
        chatOptions.web_search_options = {
          mode: 'on',
          max_resources: 5,
        };
      }

      const response = await window.puter.ai.chat(conversationRef.current, chatOptions);

      // Initialize empty assistant message for streaming
      const assistantMessage: Message = {
        role: 'assistant',
        content: '',
        isStreaming: true
      };

      // Add empty message to start showing the bubble
      conversationRef.current = [...conversationRef.current, assistantMessage];
      setMessages((prev) => [...prev, assistantMessage]);
      setStatus('thinking'); // Keep thinking status while first tokens arrive

      let fullContent = '';
      let isFirstChunk = true;

      // Handle streaming response
      if (isAsyncIterable(response)) {
        for await (const part of response) {
          if (isFirstChunk) {
            setStatus('ready'); // Clear thinking status once we start getting text
            isFirstChunk = false;
          }

          const text = typeof part === 'string' ? part : (part?.text || '');
          fullContent += text;

          // Update message in real-time
          setMessages((prev) => {
            const newMessages = [...prev];
            const lastMsg = newMessages[newMessages.length - 1];
            if (lastMsg && lastMsg.role === 'assistant') {
              lastMsg.content = fullContent;
            }
            return newMessages;
          });
        }
      } else {
        // Fallback for non-streaming response (e.g. some models might not support it yet)
        const extractContent = (response: any): string => {
          if (!response?.message) return 'No response.';
          const message = response.message;
          if (typeof message === 'string') return message;
          if (typeof message === 'object' && message !== null) {
            if (typeof message.content === 'string') return message.content;
            if (Array.isArray(message.content) && message.content[0]?.text) {
              return message.content[0].text;
            }
            if (typeof message.content === 'object' && 'text' in message.content) {
              return message.content.text;
            }
          }
          return 'No response.';
        };

        const answer = extractContent(response);
        fullContent = answer;
        setStatus('ready');
      }

      // Final update to clear streaming flag
      const finalMessage: Message = {
        role: 'assistant',
        content: fullContent,
      };

      // Update ref and state one last time
      conversationRef.current[conversationRef.current.length - 1] = finalMessage;
      setMessages((prev) => {
        const newMessages = [...prev];
        newMessages[newMessages.length - 1] = finalMessage;
        return newMessages;
      });

    } catch (error: any) {
      console.error('Error calling AI:', error);

      let errorText = 'Failed to get response';
      if (error instanceof Error) {
        errorText = error.message;
      } else if (error?.error?.message) {
        // Handle Puter API error format: { success: false, error: { message: "..." } }
        errorText = error.error.message;
      } else if (error?.message) {
        errorText = error.message;
      } else if (typeof error === 'object') {
        try {
          errorText = JSON.stringify(error);
        } catch (e) {
          errorText = 'Unknown error object';
        }
      } else if (typeof error === 'string') {
        errorText = error;
      }

      const errorMessage: Message = {
        role: 'assistant',
        content: `Error: ${errorText}`,
      };
      setMessages((prev) => [...prev, errorMessage]);
      setStatus('error');
      setTimeout(() => setStatus('ready'), 3000);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="flex h-screen bg-[#131314] text-[#e3e3e3]">
      <div className="hidden md:flex md:w-64 bg-[#1e1f20] border-r border-[#363739] flex-col p-4">
        <div className="mb-6">
          <div className="text-2xl font-semibold mb-2 font-robotic">AI Nigga</div>
          <div className="flex items-center gap-2 px-3 py-2 bg-[#28292a] rounded-lg border border-[#363739]">
            <span className="text-2xl">{model.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium truncate">{model.name}</div>
              <div className="text-xs text-[#9da0a5] truncate capitalize">
                {model.provider}
              </div>
            </div>
          </div>
        </div>

        <button
          onClick={() => {
            cleanupSessionFiles();
            onBack();
          }}
          className="flex items-center gap-2 px-4 py-2 rounded-lg hover:bg-[#28292a] transition-colors text-[#9da0a5] hover:text-[#e3e3e3]"
        >
          <ArrowLeft size={18} />
          <span>Back to Models</span>
        </button>
      </div>

      <div className="flex-1 flex flex-col">
        <div className="md:hidden bg-[#1e1f20] border-b border-[#363739] px-4 py-3 flex items-center gap-3">
          <button
            onClick={() => {
              cleanupSessionFiles();
              onBack();
            }}
            className="p-2 rounded-lg hover:bg-[#28292a] transition-colors text-[#9da0a5] hover:text-[#e3e3e3]"
          >
            <ArrowLeft size={20} />
          </button>
          <div className="flex items-center gap-2 flex-1">
            <span className="text-2xl">{model.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium truncate">{model.name}</div>
              <div className="text-xs text-[#9da0a5] truncate capitalize">
                {model.provider}
              </div>
            </div>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-4 md:px-6 py-8">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center px-4">
              <div className="text-6xl mb-4">{model.icon}</div>
              <h2 className="text-2xl font-semibold mb-2">{model.name}</h2>
              <p className="text-[#9da0a5] max-w-md">
                Start a conversation with {model.name}. Type your message below
                to begin.
              </p>
            </div>
          ) : (
            <div ref={messagesContainerRef} className="max-w-4xl mx-auto space-y-6">
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'
                    }`}
                >
                  <div
                    className={`max-w-[85%] md:max-w-[80%] rounded-2xl px-4 py-3 ${message.role === 'user'
                      ? 'bg-[#6366f1] text-white'
                      : 'bg-transparent text-[#e3e3e3]'
                      }`}
                  >
                    {message.role === 'assistant' ? (
                      <>
                        <div
                          className="prose prose-invert prose-sm max-w-none"
                          dangerouslySetInnerHTML={{
                            __html: renderMarkdown(typeof message.content === 'string' ? message.content : (Array.isArray(message.content) ? message.content.map(p => p.type === 'text' ? p.text : '').join('') : '')),
                          }}
                        />
                        {message.videoUrl && (
                          <div className="mt-4">
                            <video
                              src={message.videoUrl}
                              controls
                              className="w-full rounded-lg border border-[#363739]"
                              autoPlay
                            />
                          </div>
                        )}
                        <button
                          type="button"
                          onClick={() => handleCopyResponse(message.content, index)}
                          className="copy-response-btn"
                        >
                          {copiedResponseIndex === index ? 'Copied response' : 'Copy response'}
                        </button>
                      </>
                    ) : ( /* User message */
                      <div className="relative">
                        {/* Display attachments if present (only for user messages in this UI implementation) */}
                        {message.attachments && message.attachments.length > 0 && (
                          <div className="mb-3 flex flex-wrap gap-2">
                            {message.attachments.map((att) => (
                              <div
                                key={att.id}
                                className="flex items-center gap-2 bg-[#ffffff20] border border-[#ffffff30] rounded-lg p-2 max-w-[200px]"
                              >
                                {att.previewUrl && att.isImage ? (
                                  <img
                                    src={att.previewUrl}
                                    alt={att.name}
                                    className="w-10 h-10 object-cover rounded"
                                  />
                                ) : (
                                  <div className="w-10 h-10 bg-[#ffffff10] rounded flex items-center justify-center">
                                    <span className="text-lg">📄</span>
                                  </div>
                                )}
                                <div className="flex-1 min-w-0 overflow-hidden">
                                  <div className="text-xs font-medium truncate" title={att.name}>
                                    {att.name}
                                  </div>
                                  <div className="text-[10px] opacity-70">
                                    {formatFileSize(att.size)}
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                        <div
                          className={`whitespace-pre-wrap user-message-content ${expandedMessages.has(index) ? '' : 'max-h-[7.5rem] overflow-hidden'} ${animatingMessages.has(index) ? 'collapsing' : ''}`}
                        >
                          {typeof message.content === 'string' ? message.content : ''}
                        </div>
                        {message.content.split('\n').length > 5 && (
                          <div
                            className={`absolute bottom-0 left-0 right-0 h-10 bg-gradient-to-t from-[#6366f1] to-transparent user-message-fade ${expandedMessages.has(index) || animatingMessages.has(index) ? 'hiding' : ''}`}
                          ></div>
                        )}
                        {message.content.split('\n').length > 5 && (
                          <button
                            type="button"
                            onClick={() => toggleExpandMessage(index)}
                            className={`absolute bottom-2 right-2 px-3 py-1 text-xs font-medium text-white bg-[#6366f1]/80 hover:bg-[#6366f1] rounded-md transition-colors expand-collapse-btn ${expandedMessages.has(index) || animatingMessages.has(index) ? 'hidden' : ''} ${!animatingMessages.has(index) && !expandedMessages.has(index) ? 'showing' : ''}`}
                          >
                            Expand
                          </button>
                        )}
                        {expandedMessages.has(index) && message.content.split('\n').length > 5 && (
                          <button
                            type="button"
                            onClick={() => toggleExpandMessage(index)}
                            className={`mt-2 px-3 py-1 text-xs font-medium text-white bg-[#6366f1]/80 hover:bg-[#6366f1] rounded-md transition-colors expand-collapse-btn ${animatingMessages.has(index) ? 'collapsing' : ''} ${!animatingMessages.has(index) ? 'showing' : ''}`}
                          >
                            Collapse
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        <div
          className="border-t border-[#363739] bg-gradient-to-t from-[#1e1f20] to-[#131314]"
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
        >
          <div className="max-w-4xl mx-auto p-4">
            {/* Attachment Preview Area */}
            {attachments.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-2">
                {attachments.map((attachment) => (
                  <div
                    key={attachment.id}
                    className="relative group bg-[#28292a] border border-[#363739] rounded-lg p-2 flex items-center gap-2 max-w-xs attachment-preview attachment-item-enter"
                  >
                    {attachment.previewUrl && attachment.isImage ? (
                      <img
                        src={attachment.previewUrl}
                        alt={attachment.name}
                        className="w-12 h-12 object-cover rounded"
                      />
                    ) : (
                      <div className="w-12 h-12 bg-[#363739] rounded flex items-center justify-center file-type-icon">
                        <Paperclip size={16} className="text-[#9da0a5]" />
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-[#e3e3e3] truncate">{attachment.name}</div>
                      <div className="text-xs text-[#9da0a5] file-size-text">{formatFileSize(attachment.size)}</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeAttachment(attachment.id)}
                      className="opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-[#363739] rounded attachment-remove-btn"
                    >
                      <X size={14} className="text-[#9da0a5]" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Drag and Drop Overlay */}
            {isDragging && (
              <div className="absolute inset-0 bg-[#6366f1]/10 border-2 border-dashed border-[#6366f1] rounded-2xl flex items-center justify-center z-10 backdrop-blur-sm drop-zone-overlay">
                <div className="text-center">
                  <Paperclip size={48} className="text-[#6366f1] mx-auto mb-2" />
                  <p className="text-[#6366f1] font-medium">Drop files here</p>
                  <p className="text-[#9da0a5] text-sm">Support images and documents</p>
                </div>
              </div>
            )}

            <div className="bg-[#28292a] rounded-2xl border border-[#363739] overflow-hidden relative input-with-attachments">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                onPaste={handlePaste}
                placeholder={`Message ${model.name}...`}
                className="w-full bg-transparent px-4 py-3 text-[#e3e3e3] placeholder-[#9da0a5] resize-none focus:outline-none"
                rows={1}
                style={{ minHeight: '48px', maxHeight: '200px' }}
              />

              <div className="flex items-end justify-between px-4 pb-3 gap-4 flex-wrap">
                <div className="flex flex-col items-center gap-1 text-center flex-shrink-0">
                  <button
                    type="button"
                    onClick={triggerFileSelect}
                    className="p-2 text-[#9da0a5] hover:text-[#e3e3e3] hover:bg-[#363739] rounded-lg transition-colors paperclip-btn"
                    title="Attach files"
                    aria-label="Attach files"
                  >
                    <Paperclip size={18} />
                  </button>
                </div>
                <button
                  onClick={sendMessage}
                  disabled={!input.trim() || status === 'thinking'}
                  className="flex items-center gap-2 px-4 py-2 bg-[#6366f1] text-white rounded-lg font-medium text-sm hover:bg-[#5558e3] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {status === 'thinking' ? (
                    <>
                      <Loader2 size={16} className="animate-spin" />
                      <span>Thinking</span>
                    </>
                  ) : (
                    <>
                      <Send size={16} />
                      <span>Send</span>
                    </>
                  )}
                </button>
              </div>

              {/* Hidden File Input */}
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept="image/*,.pdf,.doc,.docx,.txt,.md"
                onChange={handleFileSelect}
                className="hidden"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
