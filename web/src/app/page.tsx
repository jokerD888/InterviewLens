// Server Component. Pre-renders the company list on the server so first paint
// has data. Client interactivity is delegated to <BrowserShell />.
import { ssrFetch } from "@/lib/server-api";
import type { Company } from "@/lib/api";
import { BrowserShell } from "@/components/browser-shell";

export const dynamic = "force-dynamic"; // always read fresh from FastAPI

type SearchParams = { company?: string; position?: string; period?: string };

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  let companies: Company[] = [];
  try {
    companies = await ssrFetch<Company[]>("/companies?with_counts=true&limit=200");
  } catch (e) {
    // Render UI even if API is down so the shell still appears.
    companies = [];
  }
  return (
    <BrowserShell
      initialCompanies={companies}
      initialCompany={sp.company ?? null}
      initialPosition={sp.position ?? null}
      initialPeriod={sp.period ?? "all"}
      apiDown={companies.length === 0}
    />
  );
}
