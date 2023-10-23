import {
  DragDrop,
  Dashboard,
  GoldenRetriever,
  ImageEditor,
  StatusBar,
  Tus,
  Uppy,
} from "./vendored/uppy-v3.17.0.min.mjs";
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
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(url);
      btnShare.className = "copied";
      await new Promise((resolve) => setTimeout(resolve, 800));
      btnShare.className = "";
    }
  });

  const btnPreview = document.getElementById("preview");
  btnPreview.disabled = !details.files.length;
  btnPreview.addEventListener("click", (e) => {
    const filesByDay = details.files.reduce((acc, file) => {
      const day = new Date(file.modified * 1000).toDateString();
      if (!acc.has(day)) {
        acc.set(day, []);
      }
      acc.get(day).push(file);
      return acc;
    }, new Map());

    let content = `<h3>List of ${details.files.length} file${
      details.files.length > 1 ? "s" : ""
    }</h3>`;
    for (const day of filesByDay.keys()) {
      content += `<p>Uploaded on ${day}</p><ul>`;
      for (const file of filesByDay.get(day)) {
        content += `<li class="filelist">${
          file.filename
        } <span class="size">(${humanFileSize(file.size)})</span></li>`;
      }
      content += "</ul>";
    }
    const modal = new tingle.modal();
    modal.setContent(content);
    modal.open();
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
  const uppyNote = `This Besace temporary shared folder already contains ${
    details.files.length
  } file${details.files.length > 1 ? "s" : ""}. It was created ${dayjs(
    folderCreated,
  ).fromNow()} and will be permanently deleted ${dayjs(
    folderExpires,
  ).fromNow()}. Peace 💚`;

  const uppy = new Uppy({
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
