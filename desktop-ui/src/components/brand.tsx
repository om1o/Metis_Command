'use client';

import Image from 'next/image';

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
  return (
    <Image
      src="/metis-mark.png"
      width={size}
      height={size}
      alt="Metis"
      priority={size >= 48}
      className="shrink-0 object-contain drop-shadow-[0_0_14px_rgba(168,85,247,0.35)]"
      style={{ width: size, height: size }}
    />
  );
}
