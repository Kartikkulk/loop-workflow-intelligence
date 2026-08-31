import { redirect } from "next/navigation";

/** Exceptions folded into Approvals — everything needing a decision is one screen. */
export default function ExceptionsRedirect() {
  redirect("/approvals");
}
