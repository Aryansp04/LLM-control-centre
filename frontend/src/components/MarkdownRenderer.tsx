import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";

const KEYWORD_REGEX =
  /\b(const|let|var|function|return|async|await|import|from|export|default|class|interface|type|if|else|for|while|try|catch|finally|def|None|True|False|self|yield|with|as|SELECT|FROM|WHERE|INSERT|INTO|UPDATE|JOIN|ORDER|BY|GROUP|int|char|void|main|printf|scanf|include)\b/g;

function highlightCodeLine(line: string): React.ReactNode[] {
  const trimmed = line.trimStart();
  if (trimmed.startsWith("//") || trimmed.startsWith("#") || trimmed.startsWith("--")) {
    return [
      <span key="comment" className="text-[#737373]">
        {line}
      </span>,
    ];
  }

  const segments = line.split(/("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)/g);
  return segments.map((seg, idx) => {
    if (
      (seg.startsWith('"') && seg.endsWith('"')) ||
      (seg.startsWith("'") && seg.endsWith("'")) ||
      (seg.startsWith("`") && seg.endsWith("`"))
    ) {
      return (
        <span key={idx} className="text-[#d4d4d4]">
          {seg}
        </span>
      );
    }

    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    KEYWORD_REGEX.lastIndex = 0;
    while ((match = KEYWORD_REGEX.exec(seg)) !== null) {
      if (match.index > lastIndex) {
        parts.push(seg.slice(lastIndex, match.index));
      }
      parts.push(
        <span key={`${idx}-${match.index}`} className="text-[#ffffff] font-semibold">
          {match[0]}
        </span>
      );
      lastIndex = match.index + match[0].length;
    }
    if (lastIndex < seg.length) {
      parts.push(seg.slice(lastIndex));
    }
    return <React.Fragment key={idx}>{parts}</React.Fragment>;
  });
}

const CodeBlock: React.FC<{ language: string; value: string }> = ({
  language,
  value,
}) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  const lines = value.replace(/\n$/, "").split("\n");

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-white/10 bg-[#050505]">
      <div className="flex items-center justify-between border-b border-white/[0.08] bg-[#0b0b0b] px-3.5 py-2 text-xs text-[#a7a6a6]">
        <span className="font-mono-tabular">{language || "code"}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs text-[#b6b5b5] transition-colors hover:bg-white/[0.08] hover:text-[#fafafa]"
        >
          {copied ? (
            <>
              <Check className="h-3.5 w-3.5 text-[#22c55e]" strokeWidth={1.75} />
              <span>Copied</span>
            </>
          ) : (
            <>
              <Copy className="h-3.5 w-3.5" strokeWidth={1.75} />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <pre className="overflow-x-auto p-3.5 text-[13px] leading-relaxed font-mono-tabular text-[#d4d4d4]">
        <code>
          {lines.map((line, i) => (
            <div key={i} className="min-h-[1.25rem]">
              {highlightCodeLine(line)}
            </div>
          ))}
        </code>
      </pre>
    </div>
  );
};

export const MarkdownRenderer: React.FC<{ content: string }> = ({ content }) => {
  return (
    <div className="markdown-body text-sm text-[#fafafa]">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || "");
            const raw = String(children || "");
            const isBlock = Boolean(match) || raw.includes("\n");
            if (isBlock) {
              return <CodeBlock language={match?.[1] || "text"} value={raw} />;
            }
            return (
              <code
                className="rounded bg-white/[0.08] px-1.5 py-0.5 font-mono-tabular text-[12.5px] text-[#fafafa]"
                {...props}
              >
                {children}
              </code>
            );
          },
          a({ href, children }) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noreferrer"
                className="text-[#fafafa] underline decoration-white/40 underline-offset-2 hover:decoration-white"
              >
                {children}
              </a>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};
