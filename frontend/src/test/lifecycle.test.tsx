// Real integration test: mounts the ACTUAL app router (real routes, real
// TPProvider, real click handlers) in jsdom and drives through the exact
// new-patient -> finalize V1 -> upload again -> finalize V2 lifecycle via
// real userEvent clicks -- not a hand-traced simulation. This is the
// closest available substitute for a live browser click-through in an
// environment with no browser/computer-use tool and no pre-existing test
// setup (this file is what added one).
import { describe, it, expect, beforeAll, afterEach, vi } from "vitest";
import { render, screen, within, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createRouter, createMemoryHistory } from "@tanstack/react-router";
import { QueryClient } from "@tanstack/react-query";
import { routeTree } from "../routeTree.gen";
import { PROCESSING_DELAY_MS_MAX } from "@/lib/tp-mock";

// vitest.config.ts sets globals: false, so @testing-library/react's
// auto-cleanup (which only registers itself when it finds a global
// `afterEach`) never fires on its own -- without this, each test's render
// piles up in the same jsdom `document`, and a previous test's leftover
// overlay/portal can sit on top of the next test's elements with
// `pointer-events: none`, exactly the failure this explicit call fixes.
afterEach(cleanup);

beforeAll(() => {
  // jsdom doesn't implement these; Radix UI's Select touches both when
  // opening/closing. Real browsers have them, jsdom doesn't -- stub, don't
  // silence, so the test still exercises real click-to-open behavior.
  if (!window.HTMLElement.prototype.hasPointerCapture) {
    window.HTMLElement.prototype.hasPointerCapture = () => false;
  }
  if (!window.HTMLElement.prototype.scrollIntoView) {
    window.HTMLElement.prototype.scrollIntoView = () => {};
  }
});

function renderApp(initialPath: string) {
  const queryClient = new QueryClient();
  const history = createMemoryHistory({ initialEntries: [initialPath] });
  const router = createRouter({ routeTree, context: { queryClient }, history });
  render(<RouterProvider router={router} />);
  return router;
}

async function waitForProcessingToClear() {
  await vi.waitFor(
    () => expect(screen.queryAllByText(/Agent reviewing/).length).toBe(0),
    { timeout: PROCESSING_DELAY_MS_MAX + 2000, interval: 200 },
  );
}

describe("V/U lifecycle: new patient through two finalized versions, one unified review page", () => {
  it("walks the full real click-through", async () => {
    const user = userEvent.setup();
    renderApp("/upload");

    // ---- Step 1: new patient, create U1 against the not-yet-real V0 slot ----
    console.log("STEP 1: fill new-patient form");
    await screen.findByText("Upload Treatment Plan");
    await user.type(screen.getByPlaceholderText(/Jordan Nakamura/), "reeda");
    await user.type(screen.getByPlaceholderText(/TP-2026-0500/), "TP584564");
    console.log("STEP 1b: click Create Attempt U1 (against V0) -- nothing is finalized yet, so this is V0, not V1");
    await user.click(screen.getByRole("button", { name: /Create Attempt U1 \(against V0\)/ }));

    // ---- Step 2: submit auto-navigates straight to the patient page ----
    console.log("STEP 2: auto-navigated to patient page");
    await screen.findByRole("heading", { name: "reeda" });
    expect(screen.getByText(/Draft · pending V0/)).toBeTruthy();
    console.log("STEP 2 done");

    // ---- Step 3: the draft is a full review page -- PDF + rule panel are
    // there immediately, but it's "processing" (no fake instant score) and
    // Finalize is disabled ----
    console.log("STEP 3: unified review page shows processing state, Finalize disabled, PDF + panel present");
    expect(screen.getAllByText(/Agent reviewing/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Agent is reviewing this attempt/)).toBeTruthy();
    expect(screen.getByText(/Page 1 of 7/)).toBeTruthy(); // PDF viewer renders even while processing
    expect((screen.getByRole("button", { name: /Finalize as V1/ }) as HTMLButtonElement).disabled).toBe(true);
    // Draft toolbar has 3 actions, mirroring the finalized version's 3
    // actions: View Summary + Send for Correction + Finalize (both disabled
    // while processing).
    expect(screen.getByRole("button", { name: /View Summary/ })).toBeTruthy();
    expect((screen.getByRole("button", { name: /Send for Correction/ }) as HTMLButtonElement).disabled).toBe(true);
    // V-only actions must not appear on a draft
    expect(screen.queryByRole("button", { name: /Mark Reviewed/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Generate Correction Email/ })).toBeNull();

    // ---- Step 4: after the simulated delay elapses, real results appear in the SAME page ----
    console.log("STEP 4: advancing past the simulated processing delay");
    await waitForProcessingToClear();
    expect(screen.getByText(/Rule check results/)).toBeTruthy();
    expect((screen.getByRole("button", { name: /Finalize as V1/ }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: /Send for Correction/ }) as HTMLButtonElement).disabled).toBe(false);
    await user.click(screen.getByRole("button", { name: /Send for Correction/ }));
    await screen.findByText(/sent for correction/i);
    console.log("STEP 4 done: processing resolved to a real result, still the same review page, Send for Correction works");

    // ---- Step 5: finalize the draft as V1, from this same page ----
    await user.click(screen.getByRole("button", { name: /Finalize as V1/ }));
    console.log("STEP 5: clicked Finalize as V1");

    // Now selected item flips to the finalized version: Draft tag gone,
    // V-only actions appear, Finalize action gone.
    await vi.waitFor(() => expect(screen.queryByText(/Draft · pending/)).toBeNull());
    expect(screen.getByRole("button", { name: /View Summary/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Mark Reviewed/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Generate Correction Email/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Finalize as/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Send for Correction/ })).toBeNull();
    expect(screen.getByRole("combobox").textContent).toMatch(/^v1 —/);
    console.log("STEP 5 done: same page now shows the finalized v1 with V-only actions");

    // ---- Step 6: upload again for the SAME patient (existing-patient flow) ----
    await user.click(screen.getByRole("link", { name: "Upload New" }));
    console.log("STEP 6: navigated back to /upload");
    await screen.findByText("Upload Treatment Plan");
    await user.click(screen.getByRole("button", { name: "Existing Patient" }));
    console.log("STEP 6b: switched to Existing Patient tab");
    await user.type(screen.getByPlaceholderText(/Name or reference ID/), "TP584564");
    console.log("STEP 6c: typed search query");
    const resultButton = await screen.findByText("reeda");
    console.log("STEP 6d: found search result, clicking");
    await user.click(resultButton);

    // Now that v1 is finalized, the next slot is a REAL V2, not V0.
    await screen.findByText(/Create Attempt U1 \(against V2\)/);
    console.log("STEP 6 done: attempt numbering reset to U1, correctly targeting real slot V2 (not V0)");
    await user.click(screen.getByRole("button", { name: /Create Attempt U1 \(against V2\)/ }));

    // ---- Step 7: auto-navigated again -- the fresh draft (U1 for V2) is
    // selected by default over the still-finalized v1 ----
    await screen.findByText(/Draft · pending V2/);
    console.log("STEP 7 done: new draft against V2 selected by default (not V0 -- v1 already exists)");

    // ---- Step 8: wait for processing, then finalize the new draft as V2 ----
    await waitForProcessingToClear();
    await user.click(screen.getByRole("button", { name: /Finalize as V2/ }));
    await vi.waitFor(() => expect(screen.queryByText(/Draft · pending/)).toBeNull());
    expect(screen.getByRole("combobox").textContent).toMatch(/^v2 —/);
    console.log("STEP 8 done: finalized as V2");

    // ---- Step 9: confirm the version picker now offers BOTH v1 and v2, grouped ----
    const trigger = screen.getByRole("combobox");
    await user.click(trigger);
    const listbox = await screen.findByRole("listbox");
    expect(within(listbox).getByText("Finalized")).toBeTruthy();
    expect(within(listbox).getByText(/^v1 —/)).toBeTruthy();
    expect(within(listbox).getByText(/^v2 —.*\(latest\)/)).toBeTruthy();
    console.log("STEP 9 done: version picker offers both v1 and v2 under a Finalized group");
  }, 45000);
});

describe("/plans list surfaces draft-only patients and their processing state", () => {
  it("shows Processing while the delay is running, then the real result, then v1 after finalizing", async () => {
    const user = userEvent.setup();
    renderApp("/upload");

    // ---- create a brand-new patient's draft (no finalized version yet) ----
    await screen.findByText("Upload Treatment Plan");
    await user.type(screen.getByPlaceholderText(/Jordan Nakamura/), "Priya Subramanian");
    await user.type(screen.getByPlaceholderText(/TP-2026-0500/), "TP-DRAFTLIST-1");
    await user.click(screen.getByRole("button", { name: /Create Attempt U1 \(against V0\)/ }));
    await screen.findByRole("heading", { name: "Priya Subramanian" });
    console.log("STEP A: draft created for Priya Subramanian, auto-navigated to her page, not yet finalized");

    // ---- go to /plans via the sidebar nav WHILE the draft is still processing ----
    await user.click(screen.getByRole("link", { name: "Treatment Plans" }));
    await screen.findByRole("heading", { name: "Treatment Plans" });
    await screen.findByText(/In progress — draft uploads not yet finalized/);
    const draftRow = screen.getByText("Priya Subramanian").closest("tr")!;
    expect(within(draftRow).getByText("U1")).toBeTruthy();
    // The whole point of this test: mid-delay, /plans must show "Processing",
    // never a fake instant score.
    expect(within(draftRow).getAllByText(/Processing/).length).toBeGreaterThan(0);
    console.log("STEP B: /plans shows 'Processing' for the draft row while the delay is still running");

    // Must NOT be duplicated into the finalized table.
    const finalizedRows = screen.queryAllByText("Priya Subramanian");
    expect(finalizedRows.length).toBe(1);

    // ---- wait out the delay while still on /plans, confirm it updates to a real result ----
    await vi.waitFor(
      () => {
        const row = screen.getByText("Priya Subramanian").closest("tr")!;
        expect(within(row).queryAllByText(/Processing/).length).toBe(0);
      },
      { timeout: PROCESSING_DELAY_MS_MAX + 2000, interval: 200 },
    );
    console.log("STEP C: /plans row updated from 'Processing' to the real result once the delay completed");

    // ---- click into it from the /plans list -- same unified review page ----
    const rowAfterProcessing = screen.getByText("Priya Subramanian").closest("tr")!;
    await user.click(rowAfterProcessing);
    await screen.findByRole("heading", { name: "Priya Subramanian" });
    await screen.findByText(/Rule check results/);
    console.log("STEP D: clicked through from /plans list into the same rich review page, results visible");

    // ---- finalize as V1 from the detail page ----
    await user.click(screen.getByRole("button", { name: /Finalize as V1/ }));
    await vi.waitFor(() => expect(screen.queryByText(/Draft · pending/)).toBeNull());
    console.log("STEP E: finalized as V1");

    // ---- back to /plans: now shows as v1 in the finalized table, no longer "in progress" ----
    await user.click(screen.getByRole("link", { name: "Treatment Plans" }));
    await screen.findByRole("heading", { name: "Treatment Plans" });
    expect(screen.queryByText(/In progress — draft uploads not yet finalized/)).toBeNull();
    const nowFinalizedRow = screen.getByText("Priya Subramanian").closest("tr")!;
    expect(within(nowFinalizedRow).getByText("v1")).toBeTruthy();
    console.log("STEP F done: patient now shows as v1 in the finalized table on /plans");
  }, 20000);
});

describe("unified review page: finalized version with a pending draft against the next slot", () => {
  it("switches between the finalized version and the draft, both in the same rich view", async () => {
    const user = userEvent.setup();
    // Ethan Ramirez is seeded with v1+v2 finalized AND two drafts already
    // pending against V3 (see initialPatients in tp-mock.ts) -- exactly the
    // "both reachable from the same page" case from the spec.
    renderApp("/plans/TP-2026-0812");

    await screen.findByRole("heading", { name: "Ethan Ramirez" });
    // Newest draft (U2) wins the default selection over the finalized v2.
    await screen.findByText(/Draft · pending V3/);
    expect(screen.getByRole("combobox").textContent).toMatch(/^U2 —/);
    expect(screen.getByRole("button", { name: /Finalize as V3/ })).toBeTruthy();
    console.log("STEP A: lands on the newest pending draft (U2) by default, full rich view, Finalize as V3 present");

    // Switch to the finalized v2 via the same combined dropdown.
    await user.click(screen.getByRole("combobox"));
    let listbox = await screen.findByRole("listbox");
    expect(within(listbox).getByText("Finalized")).toBeTruthy();
    expect(within(listbox).getByText(/^Drafts pending V3/)).toBeTruthy();
    await user.click(within(listbox).getByText(/^v2 —/));

    await vi.waitFor(() => expect(screen.queryByText(/Draft · pending/)).toBeNull());
    expect(screen.getByRole("button", { name: /Mark Reviewed/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Finalize as/ })).toBeNull();
    console.log("STEP B: switched to finalized v2 in the SAME page -- V-only actions now shown, Finalize gone");

    // And back to a draft (U1) via the dropdown again.
    await user.click(screen.getByRole("combobox"));
    listbox = await screen.findByRole("listbox");
    await user.click(within(listbox).getByText(/^U1 —/));
    await screen.findByText(/Draft · pending V3/);
    expect(screen.getByRole("button", { name: /Finalize as V3/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Mark Reviewed/ })).toBeNull();
    console.log("STEP C: switched back to draft U1 in the same page -- Finalize back, V-only actions gone");
  }, 20000);
});
