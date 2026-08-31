import { redirect } from "next/navigation";

/** Renamed to Sources: it is where the data comes from, not a settings screen. */
export default function IntegrationsRedirect() {
  redirect("/sources");
}
