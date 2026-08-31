import { redirect } from "next/navigation";

/** Folded into Approvals — one screen for everything needing a decision. */
export default function ExceptionsRedirect() {
  redirect("/approvals");
}
