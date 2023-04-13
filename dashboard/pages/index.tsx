import { NetworkActivity } from "@/components/overview/networkActivity";
import { ServerStatus } from "@/components/overview/serverStatus";
import { DashboardStatus } from "@/components/overview/dashboardStatus";

export default function Page() {
  return (
    <>
      <h2 className="w-full pb-4 pt-12 text-center text-2xl font-medium">
        Network Activity
      </h2>
      <NetworkActivity />
      <h2 className="w-full pb-4 pt-12 text-center text-2xl font-medium">
        Server Status
      </h2>
      <ServerStatus />
      <h2 className="w-full pb-4 pt-12 text-center text-2xl font-medium">
        Dashboard Status
      </h2>
      <DashboardStatus />
    </>
  );
}
