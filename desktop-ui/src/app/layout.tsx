import { Metadata, Viewport } from 'next';
import { GeistSans } from 'geist/font/sans';
import { GeistMono } from 'geist/font/mono';
import './globals.css';

export const metadata: Metadata = {
  title: 'Metis Command',
  description: 'Local-first agent control plane.',
};

/* Lets env(safe-area-inset-*) work in WebViews / notched devices */
export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      data-theme="dark"
      suppressHydrationWarning
      className={`${GeistSans.className} ${GeistMono.variable} antialiased`}
    >
      <body>
        {children}
      </body>
    </html>
  );
}
