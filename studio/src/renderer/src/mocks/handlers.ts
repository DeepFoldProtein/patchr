import { http, HttpResponse, delay } from "msw";

export const handlers = [
  // Inpaint run endpoint
  http.post("/api/inpaint/run", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    console.log("[Mock] Inpaint run started:", body);

    // Simulate processing delay
    await delay(500);

    return HttpResponse.json({
      run_id: `mock-run-${Date.now()}`,
      status: "started",
      message: "Inpaint job started successfully"
    });
  }),

  // Get run status
  http.get("/api/inpaint/status/:runId", async ({ params }) => {
    await delay(200);
    const { runId } = params;

    return HttpResponse.json({
      run_id: runId,
      step: Math.floor(Math.random() * 60),
      of: 60,
      eta_s: Math.floor(Math.random() * 120),
      running: true,
      message: "Processing..."
    });
  }),

  // Get preview frames
  http.get("/api/preview/:runId", async ({ params }) => {
    await delay(300);
    const { runId } = params;

    return HttpResponse.json({
      run_id: runId,
      frames: [
        {
          step: 10,
          data: "MOCK PDB DATA",
          score: 0.85,
          timestamp: new Date().toISOString()
        },
        {
          step: 20,
          data: "MOCK PDB DATA",
          score: 0.87,
          timestamp: new Date().toISOString()
        }
      ]
    });
  }),

  // Export view (MVS)
  http.get("/api/view/export", async () => {
    await delay(200);

    return HttpResponse.json({
      view: {
        version: "1.0",
        _molviewspec_version: "1.0.0",
        nodes: [
          {
            type: "data",
            id: "structure-1",
            params: {
              source: "mock",
              format: "pdb"
            }
          },
          {
            type: "representation",
            id: "repr-1",
            params: {
              style: "cartoon",
              colorTheme: "chain"
            }
          }
        ],
        metadata: {
          timestamp: new Date().toISOString(),
          description: "Mock view state",
          author: "Patchr Studio"
        }
      }
    });
  }),

  // Import view (MVS)
  http.post("/api/view/import", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    console.log("[Mock] View import:", body);
    await delay(200);

    return HttpResponse.json({
      success: true,
      message: "View imported successfully"
    });
  }),

  // Validate MVS
  http.post("/api/view/validate", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    console.log("[Mock] View validation:", body);
    await delay(150);

    return HttpResponse.json({
      valid: true,
      errors: [],
      warnings: []
    });
  }),

  // Auto-detect missing regions
  http.post("/api/mask/detect", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    console.log("[Mock] Mask detection:", body);
    await delay(400);

    return HttpResponse.json({
      detected: [
        {
          chain: "A",
          residues: [10, 11, 12, 13, 14]
        },
        {
          chain: "B",
          residues: [45, 46, 47]
        }
      ]
    });
  }),

  // Refine structure
  http.post("/api/refine/run", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    console.log("[Mock] Refine started:", body);
    await delay(600);

    return HttpResponse.json({
      refine_id: `mock-refine-${Date.now()}`,
      result: "MOCK REFINED PDB DATA",
      metrics: {
        clashScore: 0.12,
        ramachandranFavored: 98.5,
        rmsd: 0.45
      }
    });
  })
];
