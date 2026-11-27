import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { StatusBadge } from "../components/StatusBadge";
import { MarkdownRenderer } from "../components/MarkdownRenderer";
import { streamChatCompletion } from "../api/client";
import App from "../App";

describe("LLM Control Center UI & Streaming Tests", () => {
  it("renders cinematic hero stage at root and opens auth portal on Get Started", async () => {
    localStorage.clear();
    render(<App />);
    expect(
      await screen.findByText(/The Next Layer/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/of Intelligence/i)).toBeInTheDocument();

    const getStartedBtns = screen.getAllByRole("button", { name: /Get Started/i });
    fireEvent.click(getStartedBtns[0]);

    expect(
      await screen.findByText(/Sign in to workspace/i)
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Create an account/i }));
    expect(
      await screen.findByText(/Create operator account/i)
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();
  });

  it("renders distinct status badges for operational, invalid_credentials, and rate_limited", () => {
    const { rerender } = render(<StatusBadge status="operational" />);
    expect(screen.getByText("Operational")).toBeInTheDocument();

    rerender(<StatusBadge status="invalid_credentials" />);
    expect(screen.getByText("Invalid key")).toBeInTheDocument();

    rerender(<StatusBadge status="rate_limited" />);
    expect(screen.getByText("Rate limited")).toBeInTheDocument();
  });

  it("renders Markdown with syntax-highlighted code blocks", () => {
    const md = "Here is code:\n\n```python\ndef compute():\n    return 'ok'\n```";
    render(<MarkdownRenderer content={md} />);
    expect(screen.getByText("Here is code:")).toBeInTheDocument();
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByText("def")).toBeInTheDocument();
  });

  it("parses Server-Sent Event token frames across stream chunks", async () => {
    const encoder = new TextEncoder();
    const chunks = [
      'event: stream_start\ndata: {"stream_id":"str_1","request_id":"req_1","conversation_id":"conv_1","conversation_title":"Test","user_message_id":"u1","assistant_message_id":"a1","provider_key":"openai","requested_model":"gpt-4o-mini","omitted_context_messages":0}\n\n',
      'event: token\ndata: {"delta":"Hello ","actual_model":"gpt-4o-mini"}\n\n',
      'event: token\ndata: {"delta":"world!","actual_model":"gpt-4o-mini"}\n\n',
      'event: stream_end\ndata: {"total_tokens":12,"latency_ms":145}\n\n',
    ];

    const stream = new ReadableStream({
      start(controller) {
        for (const c of chunks) {
          controller.enqueue(encoder.encode(c));
        }
        controller.close();
      },
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      })
    );

    const tokens: string[] = [];
    let endedTokens = 0;

    await streamChatCompletion(
      { provider_key: "openai", model_id: "gpt-4o-mini", message: "Hi" },
      {
        onToken: (delta) => tokens.push(delta),
        onEnd: (tel) => {
          endedTokens = Number(tel.total_tokens);
        },
      }
    );

    expect(tokens.join("")).toBe("Hello world!");
    expect(endedTokens).toBe(12);
    fetchSpy.mockRestore();
  });
});
