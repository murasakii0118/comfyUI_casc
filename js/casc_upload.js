import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "comfyUI_casc.upload",
    async nodeCreated(node) {
        if (node.comfyClass !== "casc_input") return;
        const fileWidget = node.widgets?.find((widget) => widget.name === "casc_file");
        if (!fileWidget) return;

        const originalComputeSize = fileWidget.computeSize;
        fileWidget.computeSize = () => [0, 0];
        fileWidget.hidden = true;
        const uploadButton = node.addWidget("button", "点击上传 CASC 文件", "点击上传", async () => {
            const input = document.createElement("input");
            input.type = "file";
            input.accept = ".casc,application/octet-stream";
            input.onchange = async () => {
                const file = input.files?.[0];
                if (!file) return;
                const form = new FormData();
                form.append("file", file, file.name);
                uploadButton.name = "上传中...";
                node.setDirtyCanvas(true, true);
                try {
                    const response = await fetch("/comfyui_casc/upload", { method: "POST", body: form });
                    const result = await response.json();
                    if (!response.ok) throw new Error(result.error || "上传失败");
                    fileWidget.value = result.value;
                    fileWidget.callback?.(result.value);
                    uploadButton.name = `已选择: ${result.filename}`;
                    node.setDirtyCanvas(true, true);
                } catch (error) {
                    uploadButton.name = "点击上传 CASC 文件";
                    alert(`CASC 上传失败: ${error.message || error}`);
                    node.setDirtyCanvas(true, true);
                }
            };
            input.click();
        });
        uploadButton.serialize = true;
        uploadButton.options = uploadButton.options || {};
        uploadButton.options.serialize = true;
        if (fileWidget.value) uploadButton.name = `已选择: ${fileWidget.value.split("/").pop()}`;
        node.setDirtyCanvas(true, true);
        void originalComputeSize;
    },
});
app.registerExtension({
    name: "comfyUI_casc.identity_viewer",
    nodeCreated(node) {
        if (node.comfyClass !== "casc_identityviewer") return;
        node.properties = node.properties || {};
        node.properties.cascIdentityLines = ["执行后显示身份列表"];
        node.size = [Math.max(node.size?.[0] ?? 260, 300), Math.max(node.size?.[1] ?? 120, 150)];
        const previousExecuted = node.onExecuted;
        node.onExecuted = function (message) {
            previousExecuted?.apply(this, arguments);
            const lines = message?.text ?? message?.ui?.text ?? [];
            this.properties.cascIdentityLines = Array.isArray(lines) ? lines : [String(lines)];
            this.setSize?.([Math.max(this.size[0], 300), Math.max(100, 48 + this.properties.cascIdentityLines.length * 22)]);
            this.setDirtyCanvas?.(true, true);
        };
        const previousDrawForeground = node.onDrawForeground;
        node.onDrawForeground = function (ctx) {
            previousDrawForeground?.apply(this, arguments);
            if (this.flags?.collapsed) return;
            const lines = this.properties?.cascIdentityLines ?? [];
            ctx.save();
            ctx.fillStyle = "#b8c8de";
            ctx.font = "13px sans-serif";
            ctx.fillText("身份索引 / 名称", 12, 34);
            ctx.fillStyle = "#e7f0ff";
            lines.forEach((line, index) => ctx.fillText(String(line), 14, 54 + index * 22));
            ctx.restore();
        };
    },
});