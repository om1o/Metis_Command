'use client';

import { useId } from 'react';

export function Wordmark({
  size = 'md',
  className = '',
}: {
  size?: 'sm' | 'md' | 'large';
  className?: string;
}) {
  const cls = size === 'large' ? 'mw-large' : size === 'sm' ? 'mw-sm' : 'mw-md';
  return (
    <span className={`metis-wordmark ${cls} ${className}`} aria-label="METIS">
      METIS
    </span>
  );
}

export function Mark({ size = 24 }: { size?: number }) {
  const id = useId().replace(/:/g, '-');
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      role="img"
      aria-label="Metis"
      className="shrink-0"
    >
      <defs>
        <linearGradient id={`${id}-deep`} x1="50%" y1="0%" x2="50%" y2="100%">
          <stop offset="0%" stopColor="#a78bfa" />
          <stop offset="40%" stopColor="#7c3aed" />
          <stop offset="100%" stopColor="#3b0764" />
        </linearGradient>
        <linearGradient id={`${id}-mid`} x1="50%" y1="0%" x2="50%" y2="100%">
          <stop offset="0%" stopColor="#f0abfc" />
          <stop offset="50%" stopColor="#a855f7" />
          <stop offset="100%" stopColor="#5b21b6" />
        </linearGradient>
        <linearGradient id={`${id}-top`} x1="50%" y1="0%" x2="50%" y2="100%">
          <stop offset="0%" stopColor="#fb923c" />
          <stop offset="60%" stopColor="#f472b6" />
          <stop offset="100%" stopColor="#a855f7" stopOpacity="0" />
        </linearGradient>
        <linearGradient id={`${id}-star`} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#f5d0fe" />
          <stop offset="100%" stopColor="#7c3aed" />
        </linearGradient>
      </defs>
      <path
        d="M 8 95 C 8 32, 22 8, 35 8 C 44 8, 49 28, 50 55 C 51 28, 56 8, 65 8 C 78 8, 92 32, 92 95 L 75 95 C 75 55, 68 32, 63 32 C 58 32, 53 55, 50 78 C 47 55, 42 32, 37 32 C 32 32, 25 55, 25 95 Z"
        fill={`url(#${id}-deep)`}
      />
      <path
        d="M 18 95 C 18 38, 28 18, 36 18 C 43 18, 48 35, 50 60 C 52 35, 57 18, 64 18 C 72 18, 82 38, 82 95 L 75 95 C 75 55, 68 32, 63 32 C 58 32, 53 55, 50 78 C 47 55, 42 32, 37 32 C 32 32, 25 55, 25 95 Z"
        fill={`url(#${id}-mid)`}
        opacity="0.85"
      />
      <path
        d="M 22 22 C 24 12, 30 8, 35 8 C 42 8, 47 22, 47 32 C 38 24, 28 22, 22 22 Z"
        fill={`url(#${id}-top)`}
        opacity="0.9"
      />
      <path
        d="M 78 22 C 76 12, 70 8, 65 8 C 58 8, 53 22, 53 32 C 62 24, 72 22, 78 22 Z"
        fill={`url(#${id}-top)`}
        opacity="0.9"
      />
      <g transform="translate(50 72)">
        <path
          d="M 0 -14 L 3 -3 L 13 -2 L 4.5 3 L 8 13 L 0 6 L -8 13 L -4.5 3 L -13 -2 L -3 -3 Z"
          fill={`url(#${id}-star)`}
        />
      </g>
    </svg>
  );
}
