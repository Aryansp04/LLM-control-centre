import React, { useId } from "react";

/**
 * Exact angular S / lightning bolt geometric mark from the design spec:
 * viewBox="0 0 31.5 48.5" with metallic linearGradient + two #fdfdfd notches.
 */
export const BrandMark: React.FC<{ className?: string }> = ({ className }) => {
  const gradId = useId().replace(/:/g, "");
  return (
    <svg
      viewBox="0 0 31.5 48.5"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <defs>
        <linearGradient
          id={`bg1-${gradId}`}
          x1="8"
          y1="0"
          x2="34.1"
          y2="28.9"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="#9e9e9e" />
          <stop offset="0.28" stopColor="#a6a6a6" />
          <stop offset="0.34" stopColor="#a3a3a3" />
          <stop offset="0.40" stopColor="#3a3a3a" />
          <stop offset="0.55" stopColor="#414141" />
          <stop offset="0.60" stopColor="#7a7a7a" />
          <stop offset="0.68" stopColor="#8e8e8e" />
          <stop offset="0.80" stopColor="#a9a9a9" />
          <stop offset="0.95" stopColor="#c4c4c4" />
          <stop offset="1" stopColor="#cccccc" />
        </linearGradient>
      </defs>
      <path
        d="M21.5 0 L21.5 19.5 L31.5 19.5 L31.5 29 L10 48.5 L10 28.5 L0.5 28.5 L0.5 18.5 Z"
        fill={`url(#bg1-${gradId})`}
      />
      <rect x="0.5" y="18.5" width="9" height="10" fill="#fdfdfd" />
      <rect x="22" y="19.5" width="9.5" height="9.5" fill="#fdfdfd" />
    </svg>
  );
};

export const PartnerMark1: React.FC = () => (
  <svg viewBox="0 0 30 31" fill="none" xmlns="http://www.w3.org/2000/svg">
    <mask id="pm1-mask">
      <rect width="30" height="31" fill="white" />
      <circle cx="19.5" cy="10.5" r="5.1" fill="black" />
    </mask>
    <rect
      x="2.5"
      y="3"
      width="25"
      height="25"
      rx="5"
      stroke="currentColor"
      strokeWidth="3.2"
      mask="url(#pm1-mask)"
    />
    <circle cx="19.5" cy="10.5" r="3.1" fill="currentColor" />
  </svg>
);

export const PartnerMark2: React.FC = () => (
  <svg viewBox="0 0 25 30" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="2" width="5.2" height="26" rx="2.6" fill="currentColor" />
    <path
      d="M15 4a11 11 0 1 1 0 22V15a5.5 5.5 0 0 0 0-11Z"
      fill="currentColor"
    />
    <circle cx="15" cy="20.5" r="4.2" fill="currentColor" opacity="0.55" />
  </svg>
);

export const PartnerMark3: React.FC = () => (
  <svg viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle
      cx="14"
      cy="14"
      r="12.35"
      stroke="currentColor"
      strokeWidth="3.1"
    />
    <path
      d="M5.5 17.5C9.5 11.5 14.5 11.5 22.5 10.5"
      stroke="currentColor"
      strokeWidth="2.8"
      strokeLinecap="round"
    />
    <path
      d="M7.5 21.5C12.5 16.5 16.5 16.5 21.5 15.5"
      stroke="currentColor"
      strokeWidth="2.8"
      strokeLinecap="round"
    />
  </svg>
);

export const PartnerMark4: React.FC = () => (
  <svg viewBox="0 0 28 25.5" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M3 13.5C6.5 5.5 11.5 2.5 14 2.5C16.5 2.5 21.5 5.5 25 13.5H3Z"
      fill="currentColor"
    />
    <path
      d="M2 18.2C7 15.8 11 20.6 14 18.2C17 15.8 21 20.6 26 18.2"
      stroke="currentColor"
      strokeWidth="3.05"
      strokeLinecap="round"
    />
    <path
      d="M4 23C8.5 21 11.5 24.5 14 23C16.5 21.5 19.5 24.5 24 23"
      stroke="currentColor"
      strokeWidth="3.05"
      strokeLinecap="round"
    />
  </svg>
);
