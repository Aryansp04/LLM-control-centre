import React, { useEffect, useState } from "react";
import { Lock, ArrowRight, AlertCircle, ArrowLeft } from "lucide-react";
import { useApp } from "../context/AppContext";
import { ApiClientError } from "../api/client";
import { BrandMark } from "../components/BrandMark";
import { HERO_VIDEO_URL } from "./LandingPage";

export interface AuthPageProps {
  initialMode?: "login" | "register";
  onBackToStage?: () => void;
  onAuthenticated?: () => void;
}

export const AuthPage: React.FC<AuthPageProps> = ({
  initialMode = "login",
  onBackToStage,
  onAuthenticated,
}) => {
  const { login, register } = useApp();
  const [mode, setMode] = useState<"login" | "register">(initialMode);
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setMode(initialMode);
    setError(null);
  }, [initialMode]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      setError("Please enter a valid email address.");
      return;
    }
    if (mode === "register") {
      const derivedUser = (username.trim() || trimmedEmail.split("@")[0] || "")
        .replace(/\s+/g, "_")
        .replace(/[^A-Za-z0-9_.-]/g, "");
      if (derivedUser.length < 3) {
        setError("Username must contain at least 3 letters or numbers.");
        return;
      }
      if (password.length < 8) {
        setError("Password must be at least 8 characters long.");
        return;
      }
      setSubmitting(true);
      try {
        await register(
          trimmedEmail,
          derivedUser,
          password,
          fullName.trim() || undefined
        );
        onAuthenticated?.();
      } catch (err) {
        if (err instanceof ApiClientError) {
          setError(err.message);
        } else {
          setError("Unable to reach backend authentication service.");
        }
      } finally {
        setSubmitting(false);
      }
      return;
    }

    setSubmitting(true);
    try {
      await login(trimmedEmail, password);
      onAuthenticated?.();
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("Unable to reach backend authentication service.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-[#050505] text-[#fafafa] flex flex-col justify-between p-6 sm:p-10">
      {/* Ambient Looping CloudFront Portal Video Stage */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <video
          className="h-full w-full object-cover opacity-55"
          autoPlay
          muted
          loop
          playsInline
          preload="auto"
          aria-hidden="true"
        >
          <source src={HERO_VIDEO_URL} type="video/mp4" />
        </video>
        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(circle at 50% 45%, rgba(5,5,5,0.45) 0%, rgba(5,5,5,0.88) 72%, #050505 100%)",
          }}
        />
      </div>

      {/* Top Header */}
      <div className="relative z-10 flex items-center justify-between max-w-6xl w-full mx-auto">
        <button
          type="button"
          onClick={onBackToStage}
          className="inline-flex items-center gap-3 text-left group"
        >
          <BrandMark className="h-9 w-6" />
          <span className="text-sm font-medium text-[#fafafa]">
            The Next Layer of Intelligence
          </span>
        </button>

        {onBackToStage && (
          <button
            type="button"
            onClick={onBackToStage}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-[#b6b5b5] hover:text-[#fafafa]"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>Back to stage</span>
          </button>
        )}
      </div>

      {/* Centered Monochrome Architectural Auth Panel */}
      <div className="relative z-10 my-auto mx-auto w-full max-w-[440px] rounded-3xl border border-white/[0.12] bg-[#080808]/90 backdrop-blur-xl p-8 sm:p-9">
        {/* Explicit Sign In / Create Account Mode Switcher */}
        <div className="mb-6 grid grid-cols-2 rounded-full border border-white/[0.1] bg-[#050505] p-1">
          <button
            type="button"
            onClick={() => {
              setMode("login");
              setError(null);
            }}
            className={`h-9 rounded-full text-xs font-medium transition-colors ${
              mode === "login"
                ? "bg-[#ffffff] text-[#050505]"
                : "text-[#a7a6a6] hover:text-[#fafafa]"
            }`}
          >
            Sign In
          </button>
          <button
            type="button"
            onClick={() => {
              setMode("register");
              setError(null);
            }}
            className={`h-9 rounded-full text-xs font-medium transition-colors ${
              mode === "register"
                ? "bg-[#ffffff] text-[#050505]"
                : "text-[#a7a6a6] hover:text-[#fafafa]"
            }`}
          >
            Create Account
          </button>
        </div>

        <div className="flex items-center justify-between">
          <h1 className="text-xl font-medium tracking-tight text-[#fafafa]">
            {mode === "login" ? "Sign in to workspace" : "Create operator account"}
          </h1>
          <Lock className="h-4 w-4 text-[#8b8a8a]" strokeWidth={1.6} />
        </div>
        <p className="mt-1.5 text-xs text-[#a7a6a6] leading-relaxed">
          {mode === "login"
            ? "Access your isolated multi-provider AI control plane"
            : "API keys are Fernet-encrypted server-side and isolated per operator"}
        </p>

        {error && (
          <div
            role="alert"
            className="mt-4 flex items-start gap-2 rounded-xl border border-[#ef4444]/30 bg-[#ef4444]/10 p-3 text-xs text-[#fca5a5]"
          >
            <AlertCircle className="h-4 w-4 shrink-0 text-[#ef4444] mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate className="mt-6 space-y-4">
          <div>
            <label
              htmlFor="auth-email"
              className="block text-xs font-medium text-[#b6b5b5] mb-1.5"
            >
              Email address
            </label>
            <input
              id="auth-email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="engineer@company.com"
              className="w-full h-11 rounded-xl border border-white/[0.12] bg-[#050505] px-3.5 text-sm text-[#fafafa] placeholder-[#666666] focus:border-white/40 focus:outline-none"
            />
          </div>

          {mode === "register" && (
            <>
              <div>
                <label
                  htmlFor="auth-username"
                  className="block text-xs font-medium text-[#b6b5b5] mb-1.5"
                >
                  Username
                </label>
                <input
                  id="auth-username"
                  type="text"
                  required
                  minLength={3}
                  maxLength={50}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="alex_ops"
                  className="w-full h-11 rounded-xl border border-white/[0.12] bg-[#050505] px-3.5 text-sm text-[#fafafa] placeholder-[#666666] focus:border-white/40 focus:outline-none"
                />
              </div>
              <div>
                <label
                  htmlFor="auth-fullname"
                  className="block text-xs font-medium text-[#b6b5b5] mb-1.5"
                >
                  Full name (optional)
                </label>
                <input
                  id="auth-fullname"
                  type="text"
                  maxLength={120}
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Alex Rivera"
                  className="w-full h-11 rounded-xl border border-white/[0.12] bg-[#050505] px-3.5 text-sm text-[#fafafa] placeholder-[#666666] focus:border-white/40 focus:outline-none"
                />
              </div>
            </>
          )}

          <div>
            <label
              htmlFor="auth-password"
              className="block text-xs font-medium text-[#b6b5b5] mb-1.5"
            >
              Password
            </label>
            <input
              id="auth-password"
              type="password"
              required
              minLength={mode === "register" ? 8 : 1}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === "register" ? "Minimum 8 characters" : "••••••••"}
              className="w-full h-11 rounded-xl border border-white/[0.12] bg-[#050505] px-3.5 text-sm text-[#fafafa] placeholder-[#666666] focus:border-white/40 focus:outline-none"
            />
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="mt-3 flex h-11 w-full items-center justify-center gap-2 rounded-full bg-[#ffffff] px-5 text-sm font-medium text-[#050505] transition-colors hover:bg-[#e8e8e8] disabled:opacity-60"
          >
            <span>
              {submitting
                ? "Authenticating..."
                : mode === "login"
                ? "Sign in"
                : "Create account"}
            </span>
            <ArrowRight className="h-4 w-4" />
          </button>
        </form>

        <div className="mt-6 border-t border-white/[0.08] pt-4 text-center text-xs text-[#a7a6a6]">
          {mode === "login" ? (
            <>
              New to the platform?{" "}
              <button
                type="button"
                onClick={() => {
                  setMode("register");
                  setError(null);
                }}
                className="font-medium text-[#fafafa] hover:underline"
              >
                Create an account
              </button>
            </>
          ) : (
            <>
              Already registered?{" "}
              <button
                type="button"
                onClick={() => {
                  setMode("login");
                  setError(null);
                }}
                className="font-medium text-[#fafafa] hover:underline"
              >
                Sign in instead
              </button>
            </>
          )}
        </div>
      </div>

      {/* Footer note */}
      <div className="relative z-10 text-center text-[11px] text-[#8b8a8a]">
        Encrypted Server-Side Vault · OpenAI · Google Gemini · Anthropic Claude
      </div>
    </div>
  );
};
