import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RescueMesh AI | Hazard Overview",
  description: "District hazard data dashboard for RescueMesh AI.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
