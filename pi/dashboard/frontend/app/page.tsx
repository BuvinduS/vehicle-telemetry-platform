import ArcGauge from "@/components/ArcGauge";
import NumericReadout from "@/components/NumericReadout";
import Thermometer from "@/components/Thermometer";
import GForcePanel from "@/components/GForcePanel";
import ModeSwitcher from "@/components/ModeSwitcher";

export default function Home() {
  return (
    <main className="min-h-screen bg-bg text-ink p-8 flex flex-col gap-10">
      <ModeSwitcher />
      <div className="grid grid-cols-[1fr_auto_1fr] items-center flex-1">
        <div className="flex flex-col gap-4 justify-self-start self-start pl-4">
          <div className="flex flex-col gap-4 mt-16">
            <NumericReadout label="Throttle" value={62} unit="%" warnAt={85} />
            <NumericReadout label="Engine Load" value={78} unit="%" warnAt={70} dangerAt={90} />
            <Thermometer label="Coolant" value={92} min={0} max={130} unit="°C" warnAt={100} dangerAt={115} />
          </div>

          <div className="mt-16">
            <GForcePanel accelX={2.1} accelY={-4.3} />
          </div>
        </div>

        <div className="flex items-center gap-12">
          <ArcGauge label="Speed" value={87} min={0} max={220} unit="km/h" size={380} />
          <ArcGauge label="Engine" value={5200} min={0} max={7000} redline={6000} unit="rpm" size={380} />
        </div>

        <div />
      </div>
    </main>
  );
}