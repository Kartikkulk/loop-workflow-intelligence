"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useCurrentUser } from "@/lib/api/queries";

/** Routes that render without a session. */
const PUBLIC = ["/", "/login"];

/**
 * Keeps the console behind sign-in.
 *
 * The API refuses unauthenticated requests on its own — this is not the thing
 * protecting the data, and it must not be mistaken for it. What it does is stop
 * a signed-out person landing on a console full of error panels, which is a
 * confusing way to be told to log in.
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const me = useCurrentUser();

  const isPublic = PUBLIC.includes(pathname);
  const needsLogin = me.data?.login_required && !me.data?.signed_in;

  useEffect(() => {
    if (!isPublic && needsLogin) router.replace("/login");
  }, [isPublic, needsLogin, router]);

  // Nothing is rendered until the answer is known, so the console never flashes
  // into view before redirecting.
  if (!isPublic && me.isLoading) return null;
  if (!isPublic && needsLogin) return null;

  return <>{children}</>;
}
