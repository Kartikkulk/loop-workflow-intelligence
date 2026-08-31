import { redirect } from "next/navigation";

/** Renamed: "Observation" became "Integrations", the first step of the journey. */
export default function SourcesRedirect() {
  redirect("/integrations");
}
