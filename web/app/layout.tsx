import './globals.css';
import type { ReactNode } from 'react';

export const metadata = {
  title: 'Comics MVP Web',
  description: 'Next.js migration shell for Comics Sales MVP',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
