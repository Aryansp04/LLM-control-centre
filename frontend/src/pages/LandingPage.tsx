import React, { useEffect, useState } from "react";
import {
  BrandMark,
  PartnerMark1,
  PartnerMark2,
  PartnerMark3,
  PartnerMark4,
} from "../components/BrandMark";

export const HERO_VIDEO_URL =
  "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260808_112712_da9d53df-6d27-4b12-bdf6-aa9dc2622bdf.mp4";

interface LandingPageProps {
  isAuthenticated: boolean;
  onEnterConsole: (targetPath?: string, preferredMode?: "login" | "register") => void;
}

export const LandingPage: React.FC<LandingPageProps> = ({
  isAuthenticated,
  onEnterConsole,
}) => {
  const [menuOpen, setMenuOpen] = useState(false);
  const [archModalOpen, setArchModalOpen] = useState(false);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenuOpen(false);
        setArchModalOpen(false);
      }
    };
    const onResize = () => {
      if (window.innerWidth / Math.max(1, window.innerHeight) > 1.1) {
        setMenuOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  const handleNavAction = (
    path: string,
    preferredMode: "login" | "register" = "login"
  ) => {
    setMenuOpen(false);
    onEnterConsole(path, preferredMode);
  };

  return (
    <div className={`stage${menuOpen ? " is-open" : ""}`}>
      {/* Full-bleed CloudFront looping background video + dual measured fades */}
      <div className="plate">
        <video
          className="plate-video"
          autoPlay
          muted
          loop
          playsInline
          preload="auto"
          aria-hidden="true"
        >
          <source src={HERO_VIDEO_URL} type="video/mp4" />
        </video>
      </div>

      {/* Topbar */}
      <header className="topbar">
        <a
          href="#top"
          className="brand"
          aria-label="LLM Control Center Home"
          onClick={(e) => {
            e.preventDefault();
            if (isAuthenticated) handleNavAction("/");
          }}
        >
          <BrandMark />
        </a>

        <nav className="links" aria-label="Primary">
          <a
            href="#chat"
            onClick={(e) => {
              e.preventDefault();
              handleNavAction("/chat");
            }}
          >
            AI Chat
          </a>
          <a
            href="#providers"
            onClick={(e) => {
              e.preventDefault();
              handleNavAction("/providers");
            }}
          >
            Providers
          </a>
          <a
            href="#monitoring"
            onClick={(e) => {
              e.preventDefault();
              handleNavAction("/monitoring");
            }}
          >
            Monitoring
          </a>
          <a
            href="#analytics"
            onClick={(e) => {
              e.preventDefault();
              handleNavAction("/analytics");
            }}
          >
            Analytics
          </a>
        </nav>

        <button
          type="button"
          className="pill pill-nav"
          onClick={() =>
            handleNavAction(isAuthenticated ? "/chat" : "/overview", "register")
          }
        >
          <span>{isAuthenticated ? "Open Console" : "Get Started"}</span>
        </button>

        <button
          type="button"
          id="burger"
          className="burger"
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
          aria-controls="menu"
          onClick={() => setMenuOpen((v) => !v)}
        >
          <i />
          <i />
        </button>
      </header>

      {/* Mobile / Portrait Staggered Overlay Menu */}
      <nav
        id="menu"
        className="menu"
        aria-hidden={!menuOpen}
      >
        <div className="menu-inner">
          <div>
            <p className="menu-eyebrow">Menu</p>
            <ul className="menu-list">
              <li>
                <button type="button" onClick={() => handleNavAction("/chat")}>
                  AI Chat
                </button>
              </li>
              <li>
                <button
                  type="button"
                  onClick={() => handleNavAction("/providers")}
                >
                  Providers
                </button>
              </li>
              <li>
                <button
                  type="button"
                  onClick={() => handleNavAction("/monitoring")}
                >
                  Monitoring
                </button>
              </li>
              <li>
                <button
                  type="button"
                  onClick={() => handleNavAction("/analytics")}
                >
                  Analytics
                </button>
              </li>
            </ul>
          </div>

          <div className="menu-foot">
            <button
              type="button"
              className="pill"
              onClick={() =>
                handleNavAction(isAuthenticated ? "/chat" : "/overview", "register")
              }
            >
              <span>{isAuthenticated ? "Open Console" : "Get Started"}</span>
            </button>
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setMenuOpen(false);
                setArchModalOpen(true);
              }}
            >
              View Architecture
            </button>
          </div>
        </div>
      </nav>

      {/* Hero Composition */}
      <main className="hero">
        <h1 className="headline">
          <span>The Next Layer</span>
          <span>of Intelligence</span>
        </h1>

        <p className="sub">
          <span>A unified LLM control center to stream, monitor,</span>
          <span>and govern multi-provider AI systems in real time.</span>
        </p>

        <div className="actions">
          <button
            type="button"
            className="pill pill-cta"
            onClick={() =>
              handleNavAction(isAuthenticated ? "/chat" : "/overview", "register")
            }
          >
            <span>{isAuthenticated ? "Open Console" : "Get Started"}</span>
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() =>
              isAuthenticated
                ? handleNavAction("/monitoring")
                : setArchModalOpen(true)
            }
          >
            View Architecture
          </button>
        </div>
      </main>

      {/* Bottom 4-Mark Provider Ecosystem Strip in Measured Fade */}
      <div className="logos" aria-label="Integrated LLM Providers">
        <div className="lg lg1">
          <PartnerMark1 />
          <span className="word">OpenAI</span>
        </div>
        <div className="lg lg2">
          <PartnerMark2 />
          <span className="word">
            Gemini<span className="dot" />
          </span>
        </div>
        <div className="lg lg3">
          <PartnerMark3 />
          <span className="word">Anthropic</span>
        </div>
        <div className="lg lg4">
          <PartnerMark4 />
          <span className="word">Postgres</span>
        </div>
      </div>

      {/* Minimal Monochrome Architecture Specification Drawer */}
      {archModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-6"
          onClick={() => setArchModalOpen(false)}
        >
          <div
            className="w-full max-w-xl rounded-2xl border border-white/12 bg-[#080808] p-7 text-left select-text"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-white/10 pb-4">
              <div className="flex items-center gap-3">
                <BrandMark className="h-6 w-4" />
                <span className="text-sm font-medium text-[#fafafa]">
                  LLM Control Center — System Architecture
                </span>
              </div>
              <button
                type="button"
                onClick={() => setArchModalOpen(false)}
                className="text-xs text-[#a7a6a6] hover:text-[#fafafa]"
              >
                Close
              </button>
            </div>
            <div className="mt-5 space-y-3 text-xs leading-relaxed text-[#a7a6a6]">
              <p>
                <strong className="text-[#fafafa]">Unified Multi-Provider Engine:</strong>{" "}
                Official REST and Server-Sent Events (SSE) adapters for OpenAI,
                Google Gemini, and Anthropic Claude with capability detection,
                exponential-backoff retries, and rolling 4-hour 100% quota meters.
              </p>
              <p>
                <strong className="text-[#fafafa]">Four-Tier Telemetry & Live Bus:</strong>{" "}
                Separates Backend/DB/Redis infrastructure health from upstream API
                reachability, Fernet-encrypted account vaults, and per-model
                TTFT, throughput, and versioned cost analytics over authenticated
                WebSockets.
              </p>
            </div>
            <div className="mt-6 flex items-center justify-end gap-4 pt-2">
              <button
                type="button"
                onClick={() => setArchModalOpen(false)}
                className="text-xs font-medium text-[#a7a6a6] hover:text-[#fafafa]"
              >
                Dismiss
              </button>
              <button
                type="button"
                onClick={() => {
                  setArchModalOpen(false);
                  onEnterConsole("/");
                }}
                className="h-9 rounded-full bg-white px-5 text-xs font-medium text-[#050505] hover:bg-[#ececec]"
              >
                Enter Control Center
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
