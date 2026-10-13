import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "InterviewLens · 管理后台",
  robots: { index: false, follow: false },
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return children;
}
