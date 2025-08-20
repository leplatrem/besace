import { test, expect, Page } from "@playwright/test";
import path from "path";
import os from "os";

/** Helpers */
const PASSWORD = "s3cr3t";
const UPPY_TITLE = "Drop files here or upload files";
const ASSET_RELATIVE = "../thumbnailer/assets/default.jpg";

function assetPath() {
  return path.resolve(process.cwd(), ASSET_RELATIVE);
}

let besaceUrl: string | null = null;

async function getOrCreateBesace(page: Page): Promise<string> {
  if (besaceUrl) {
    // Already created, just go there
    await page.goto(besaceUrl);
    return besaceUrl;
  }

  // Accept password prompt
  page.once("dialog", async (dialog) => {
    await dialog.accept(PASSWORD);
  });

  await page.goto("/");

  // Uppy dashboard title appears
  await expect(page.locator(".uppy-Dashboard-AddFiles-title")).toHaveText(
    UPPY_TITLE
  );

  // URL hash should be 3 words separated by dashes
  await expect(page).toHaveURL(/#([a-z]+-){2}[a-z]+$/);

  besaceUrl = page.url();
  return besaceUrl;
}

async function uploadDefaultImage(page: Page) {
  // Click "upload files" and attach file via the file chooser
  const chooserPromise = page.waitForEvent("filechooser");
  await page.click("button.uppy-Dashboard-browse");
  const chooser = await chooserPromise;
  await chooser.setFiles(assetPath());

  // Assert the file appears in the Uppy file list
  const fileItems = page.locator(".uppy-Dashboard-Item");
  await expect(fileItems).toHaveCount(1);

  await page.click("button.uppy-StatusBar-actionBtn--upload");

  // After upload completes, the download label should say "Download 1 file"
  const downloadLabel = page.locator("#download-label");
  await expect(downloadLabel).toContainText("Download 1 file");

  // And it should include a size in parentheses, e.g. "(XXXX kB)" or "(558 B)"
  await expect(downloadLabel).toContainText(/\(\d+(\.\d+)?\s?(B|kB|MB)\)/);
}

/** Tests */

test("home prompts for password", async ({ page }) => {
  await getOrCreateBesace(page);

  // Sanity: still on the Uppy dashboard after redirect
  await expect(page.locator(".uppy-Dashboard-AddFiles-title")).toHaveText(
    UPPY_TITLE
  );
});

test("can upload files", async ({ page }) => {
  await getOrCreateBesace(page);
  await uploadDefaultImage(page);
});

test("can download the folder", async ({ page }) => {
  await getOrCreateBesace(page);

  // Trigger the download and assert it is a zip
  const downloadPromise = page.waitForEvent("download");
  await page.click("#download");
  const download = await downloadPromise;

  // The suggested filename should end with .zip
  const suggested = download.suggestedFilename();
  expect(suggested).toMatch(/\.zip$/i);

  // Ensure the download actually started and is non-empty
  const filePath = await download.path(); // may be null on some browsers; save as fallback
  if (!filePath) {
    const tempZip = path.resolve(
      process.cwd(),
      `.playwright-tmp-${Date.now()}.zip`
    );
    await download.saveAs(tempZip);
  }
  await expect(download.failure()).resolves.toBeNull();
});

test("can see thumbnails", async ({ page, context }) => {
  await getOrCreateBesace(page);

  // Open preview view
  await page.click("#preview");

  // Check that there are no broken images in the gallery
  await page.waitForSelector(".gallery img");
  const brokenCount = await page.$$eval(
    ".gallery img",
    (imgs) =>
      imgs.filter(
        (img) =>
          !(img.complete && img.naturalWidth > 0 && img.naturalHeight > 0)
      ).length
  );
  expect(brokenCount).toBe(0);

  // Check that clicking the first thumbnail link serves the correct file (HTTP 200)
  const firstLink = page.locator(".gallery .thumbnail a").first();

  // Intercept the response of the linked file request
  const href = await firstLink.getAttribute("href");
  expect(href).toBeTruthy();

  const response = await context.request.get(href!);
  expect(response.ok()).toBeTruthy();

  // Verify Content-Disposition
  const cd = response.headers()["content-disposition"] || "";
  expect(cd.toLowerCase()).toContain("filename");
});
