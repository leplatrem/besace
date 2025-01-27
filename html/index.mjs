import {
  Dashboard,
  ImageEditor,
  Tus,
  Uppy,
} from "./vendored/uppy-v3.25.2.min.mjs";
dayjs.extend(dayjs_plugin_relativeTime);

function humanFileSize(size) {
  const i = size == 0 ? 0 : Math.floor(Math.log(size) / Math.log(1024));
  return (
    (size / Math.pow(1024, i)).toFixed(2) * 1 +
    " " +
    ["B", "kB", "MB", "GB", "TB"][i]
  );
}

window.addEventListener("load", async (e) => {
  let details;

  const folderId = window.location.hash.slice(1);
  if (!folderId) {
    // User landed on home page without folder. Create one!
    document.getElementById("title").textContent = "Create new...";
    let createSecret = localStorage.getItem("create-secret");
    while (true) {
      if (!createSecret) {
        createSecret = window.prompt("Secret word?") || "";
      }
      const respRaw = await fetch("/api/folder", {
        method: "POST",
        headers: {
          Authorization: `key ${createSecret}`,
        },
      });
      if (respRaw.status < 400) {
        // Creation successful, proceed :)
        details = await respRaw.json();
        window.location.hash = details.folder;
        localStorage.setItem("create-secret", createSecret);
        break;
      } else {
        createSecret = "";
        localStorage.removeItem("create-secret");
      }
    }
  } else {
    const respRaw = await fetch(`/api/folder/${folderId}`);
    if (respRaw.status >= 400) {
      document.getElementById(
        "title",
      ).textContent = `Unknown folder ${folderId}`;
      // Exit UI load.
      return;
    }
    details = await respRaw.json();
  }

  document.getElementById("title").textContent = details.folder;

  const btnDownload = document.getElementById("download");
  btnDownload.disabled = !details.files.length;
  const size = details.files.reduce((acc, f) => {
    acc += f.size;
    return acc;
  }, 0);
  btnDownload.querySelector("#download-label").innerHTML = `Download ${
    details.files.length
  } file${details.files.length > 1 ? "s" : ""} <br/> (${humanFileSize(size)})`;
  btnDownload.addEventListener("click", (e) => {
    window.location = `/api/folder/${details.folder}/download`;
  });

  const btnShare = document.getElementById("share");
  btnShare.addEventListener("click", async (e) => {
    e.preventDefault();
    const url = window.location.href;
    if (navigator.share) {
      await navigator.share({ url });
    }
    else if (navigator.clipboard) {
      await navigator.clipboard.writeText(url);
      btnShare.className = "copied";
      await new Promise((resolve) => setTimeout(resolve, 1000));
      btnShare.className = "";
    }
  });

  const btnPreview = document.getElementById("preview");
  btnPreview.disabled = !details.files.length;
  btnPreview.addEventListener("click", (e) => {
    // Group by upload
    const minimumIntervalSeconds = 3600 * 3; // 3H between groups.
    const groups = new Map();
    let currentGroup;
    for (const file of details.files) {
      if (!currentGroup || (currentGroup - file.modified) > minimumIntervalSeconds) {
        currentGroup = file.modified;
        groups.set(currentGroup, [file]);
      } else {
        groups.get(currentGroup).push(file);
      }
    }

    let content = `<h3>List of ${details.files.length} file${
      details.files.length > 1 ? "s" : ""
    }</h3>`;
    for (const timestamp of groups.keys()) {
      const day = new Date(timestamp * 1000).toLocaleString();
      content += `
      <p>Uploaded on ${day}</p>
      <div class="gallery">`;
      for (const file of groups.get(timestamp)) {
        content += `
        <div class="thumbnail">
          <a href="/api/file/${details.folder}/${file.filename}">
            <img src="/thumbnails/${details.folder}/${file.filename}.jpg"/>
          </a>
          <div class="info">
            <p class="filename">${file.filename}</p>
            <p class="filesize">(${humanFileSize(file.size)})</p>
          </div>
        </div>`;
      }
      content += "</div>";
    }
    const modal = new tingle.modal();
    modal.setContent(content);
    modal.open();

    // Reload thumbnails if they are beeing created.
    Array.from(document.querySelectorAll(".gallery img"))
      .map((elt) => {
        elt.addEventListener("error", () => {
          setTimeout(() => {
            elt.src = elt.src;
          }, 1000);
        });
      });
  });

  if (details.files.length) {
    const lastUpdate = new Date(details.files[0].modified * 1000);
    const lastUpdateElt = document.getElementById("last-update");
    lastUpdateElt.setAttribute("title", lastUpdate.toLocaleDateString());
    lastUpdateElt.textContent = `Last upload: ${dayjs(lastUpdate).fromNow()}`;
  }

  const folderCreated = new Date(details.created * 1000);
  const folderExpires = new Date(
    (details.created + details.settings.retention_days * 3600 * 24) * 1000,
  );
  const uppyNote = `This Besace temporary shared folder contains ${
    details.files.length
  } file${details.files.length > 1 ? "s" : ""}. It was created ${dayjs(
    folderCreated,
  ).fromNow()} and will be permanently deleted ${dayjs(
    folderExpires,
  ).fromNow()}. Remember that you are uploading files to a remote computer that is not yours. Peace 💚 `;

  const uppy = new Uppy({
    restrictions: {
      maxFileSize: 1000000000, // See tusd `-max-size` command parameter
    },
    onBeforeUpload: (files) => {
      // Set folder id on uploaded files.
      Object.values(files).forEach((file) => {
        file.meta.folderId = details.folder;
      });
      return true;
    },
  });
  uppy
    .use(Dashboard, {
      inline: true,
      target: "#uppy",
      height: document.getElementById("uppy").offsetHeight - 30,
      width: document.getElementById("uppy").offsetWidth,
      note: uppyNote,
      locale: {
        strings: {
          browseFiles: "upload files",
          poweredBy: "%{uppy}",
        },
      },
    })
    .use(ImageEditor, { target: Dashboard })
    .use(Tus, {
      endpoint: window.location.href.split("#")[0] + "tusd",
    });
  uppy.on("complete", async (result) => {
    // If successful, wait and refresh.
    if (result.failed.length == 0) {
      setTimeout(() => window.location.reload(), 1000);
    }
  });
});


function onResize() {
  document.documentElement.style.setProperty("--doc-height", `${window.innerHeight}px`);
}
window.addEventListener("resize", onResize);
onResize();
