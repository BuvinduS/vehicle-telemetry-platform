import StatusBar from "@/components/StatusBar";
import LiveDashboard from "@/components/LiveDashboard";

export default function Home() {
  return (
    <main className="min-h-screen bg-bg text-ink p-8 flex flex-col gap-10">
      <StatusBar />
      <LiveDashboard />
    </main>
  );
}