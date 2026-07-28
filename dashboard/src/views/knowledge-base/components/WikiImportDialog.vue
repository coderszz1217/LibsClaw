<script setup lang="ts">
import { computed, onBeforeUnmount, shallowRef, watch } from "vue";
import { knowledgeApi } from "@/api/v1";

interface Props {
  modelValue: boolean;
  kbId: string;
}

interface WikiImportEntry {
  id: number;
  file: File;
  path: string;
  archive: boolean;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  "update:modelValue": [value: boolean];
  imported: [];
  busy: [value: boolean];
}>();

const fileInput = shallowRef<HTMLInputElement | null>(null);
const directoryInput = shallowRef<HTMLInputElement | null>(null);
const entries = shallowRef<WikiImportEntry[]>([]);
const overwrite = shallowRef(false);
const importing = shallowRef(false);
const errorMessage = shallowRef("");
const successMessage = shallowRef("");
const statusMessage = shallowRef("");
const progress = shallowRef({ current: 0, total: 0 });
let pollTimer: number | null = null;
let nextEntryId = 0;

const previewEntries = computed(() => entries.value.slice(0, 100));
const hiddenEntryCount = computed(() =>
  Math.max(0, entries.value.length - previewEntries.value.length),
);
const totalSize = computed(() =>
  entries.value.reduce((total, entry) => total + entry.file.size, 0),
);
const progressValue = computed(() => {
  if (progress.value.total <= 0) return 0;
  return Math.min(100, (progress.value.current / progress.value.total) * 100);
});

const setImporting = (value: boolean) => {
  importing.value = value;
  emit("busy", value);
};

const stopPolling = () => {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
};

const reset = () => {
  stopPolling();
  entries.value = [];
  overwrite.value = false;
  errorMessage.value = "";
  successMessage.value = "";
  statusMessage.value = "";
  progress.value = { current: 0, total: 0 };
  if (fileInput.value) fileInput.value.value = "";
  if (directoryInput.value) directoryInput.value.value = "";
};

const updateModelValue = (value: boolean) => {
  if (importing.value && !value) return;
  emit("update:modelValue", value);
};

const close = () => {
  if (importing.value) return;
  emit("update:modelValue", false);
};

const formatFileSize = (bytes: number) => {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 2)} ${units[unitIndex]}`;
};

const isMarkdown = (name: string) => {
  const normalized = name.toLowerCase();
  return (
    normalized.endsWith(".md") ||
    normalized.endsWith(".markdown") ||
    normalized.endsWith(".mdx")
  );
};

const addEntries = (newEntries: WikiImportEntry[]) => {
  const merged = [...entries.value];
  newEntries.forEach((entry) => {
    if (entry.archive) {
      merged.push(entry);
      return;
    }
    const existingIndex = merged.findIndex(
      (existing) => !existing.archive && existing.path === entry.path,
    );
    if (existingIndex >= 0) merged[existingIndex] = entry;
    else merged.push(entry);
  });
  entries.value = merged;
  errorMessage.value = "";
  successMessage.value = "";
};

const selectFiles = (event: Event) => {
  const target = event.target as HTMLInputElement;
  const files = Array.from(target.files || []);
  const accepted = files
    .filter(
      (file) =>
        isMarkdown(file.name) || file.name.toLowerCase().endsWith(".zip"),
    )
    .map((file) => {
      const archive = file.name.toLowerCase().endsWith(".zip");
      nextEntryId += 1;
      return {
        id: nextEntryId,
        file,
        path: archive ? "" : file.name,
        archive,
      };
    });
  addEntries(accepted);
  if (accepted.length !== files.length) {
    errorMessage.value = `已忽略 ${
      files.length - accepted.length
    } 个不支持的文件。`;
  }
  target.value = "";
};

const selectDirectory = (event: Event) => {
  const target = event.target as HTMLInputElement;
  const files = Array.from(target.files || []);
  const accepted: WikiImportEntry[] = [];
  let ignored = 0;

  files.forEach((file) => {
    if (!isMarkdown(file.name)) {
      ignored += 1;
      return;
    }
    const parts = file.webkitRelativePath
      .replace(/\\/g, "/")
      .split("/")
      .filter(Boolean);
    const path = parts.length > 1 ? parts.slice(1).join("/") : file.name;
    nextEntryId += 1;
    accepted.push({ id: nextEntryId, file, path, archive: false });
  });

  addEntries(accepted);
  if (ignored > 0) {
    errorMessage.value = `已忽略文件夹中的 ${ignored} 个非 Markdown 文件。`;
  }
  target.value = "";
};

const removeEntry = (id: number) => {
  entries.value = entries.value.filter((entry) => entry.id !== id);
};

const finishImport = (message: string) => {
  stopPolling();
  setImporting(false);
  statusMessage.value = "";
  progress.value = { current: 0, total: 0 };
  successMessage.value = message;
  emit("imported");
};

const failImport = (message: string) => {
  stopPolling();
  setImporting(false);
  statusMessage.value = "";
  errorMessage.value = message;
};

const pollTask = async (taskId: string) => {
  try {
    const response = await knowledgeApi.task(taskId);
    if (response.data.status !== "ok") {
      failImport(response.data.message || "读取导入任务状态失败。");
      return;
    }

    const task = response.data.data;
    const taskStatus = task?.status;
    if (taskStatus === "completed") {
      const importedCount =
        task.result?.imported_count ??
        task.result?.success_count ??
        task.result?.page_count;
      finishImport(
        typeof importedCount === "number"
          ? `Wiki 导入完成，共导入 ${importedCount} 个页面。`
          : "Wiki 导入完成。",
      );
      return;
    }
    if (taskStatus === "failed") {
      const taskError = task.error?.message || task.error || "Wiki 导入失败。";
      failImport(String(taskError));
      return;
    }

    const taskProgress = task?.progress || {};
    statusMessage.value =
      taskProgress.stage ||
      (taskStatus === "pending" ? "等待处理..." : "正在导入 Wiki...");
    progress.value = {
      current: Number(taskProgress.current || taskProgress.file_index || 0),
      total: Number(taskProgress.total || taskProgress.file_count || 0),
    };
    pollTimer = window.setTimeout(() => void pollTask(taskId), 750);
  } catch (error: any) {
    failImport(
      error.response?.data?.message ||
        error.message ||
        "读取导入任务状态失败。",
    );
  }
};

const submit = async () => {
  if (entries.value.length === 0 || importing.value) return;

  errorMessage.value = "";
  successMessage.value = "";
  statusMessage.value = "正在提交导入任务...";
  progress.value = { current: 0, total: entries.value.length };
  setImporting(true);

  try {
    const formData = new FormData();
    entries.value.forEach((entry) => {
      formData.append("files", entry.file);
      formData.append("paths", entry.path);
    });
    formData.append("overwrite", String(overwrite.value));

    const response = await knowledgeApi.importWiki(props.kbId, formData);
    if (response.data.status !== "ok") {
      failImport(response.data.message || "创建 Wiki 导入任务失败。");
      return;
    }

    const taskId = response.data.data?.task_id;
    if (!taskId) {
      finishImport("Wiki 导入完成。");
      return;
    }
    statusMessage.value = "等待导入任务开始...";
    await pollTask(taskId);
  } catch (error: any) {
    failImport(
      error.response?.data?.message ||
        error.message ||
        "创建 Wiki 导入任务失败。",
    );
  }
};

watch(
  () => props.modelValue,
  (open) => {
    if (open && !importing.value) reset();
  },
);

onBeforeUnmount(() => {
  stopPolling();
  if (importing.value) emit("busy", false);
});
</script>

<template>
  <v-dialog
    :model-value="modelValue"
    max-width="760"
    :persistent="importing"
    @update:model-value="updateModelValue"
  >
    <v-card>
      <v-card-title class="text-h3 pa-4 pb-0 pl-6 d-flex align-center">
        <span>导入 Wiki</span>
        <v-spacer />
        <v-btn
          icon="mdi-close"
          variant="text"
          :disabled="importing"
          @click="close"
        />
      </v-card-title>

      <v-card-text class="pa-6">
        <v-alert type="info" variant="tonal" density="compact" class="mb-4">
          可选择多个 Markdown、ZIP
          压缩包或整个文件夹。文件数量不设上限；文件夹根目录会被去掉，其下分类结构会完整保留。为防止压缩炸弹，单次原始文件总量最多
          512 MiB，ZIP 展开后最多 2 GiB。
        </v-alert>

        <div class="import-actions mb-4">
          <v-btn
            prepend-icon="mdi-file-multiple-outline"
            variant="outlined"
            :disabled="importing"
            @click="fileInput?.click()"
          >
            选择 Markdown / ZIP
          </v-btn>
          <v-btn
            prepend-icon="mdi-folder-upload-outline"
            variant="outlined"
            :disabled="importing"
            @click="directoryInput?.click()"
          >
            选择文件夹
          </v-btn>
          <input
            ref="fileInput"
            type="file"
            hidden
            multiple
            accept=".md,.markdown,.mdx,.zip"
            @change="selectFiles"
          />
          <input
            ref="directoryInput"
            type="file"
            hidden
            multiple
            accept=".md,.markdown,.mdx"
            webkitdirectory=""
            directory=""
            @change="selectDirectory"
          />
        </div>

        <v-alert
          v-if="errorMessage"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ errorMessage }}
        </v-alert>
        <v-alert
          v-if="successMessage"
          type="success"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ successMessage }}
        </v-alert>

        <div v-if="entries.length > 0" class="selected-files">
          <div class="d-flex align-center justify-space-between mb-2">
            <span class="text-subtitle-2">
              已选择 {{ entries.length }} 个文件，共
              {{ formatFileSize(totalSize) }}
            </span>
            <v-btn
              size="small"
              variant="text"
              :disabled="importing"
              @click="entries = []"
            >
              清空
            </v-btn>
          </div>
          <v-list class="file-preview" density="compact" border rounded>
            <v-list-item
              v-for="entry in previewEntries"
              :key="entry.id"
              :title="entry.path || entry.file.name"
              :subtitle="formatFileSize(entry.file.size)"
              :prepend-icon="
                entry.archive
                  ? 'mdi-folder-zip-outline'
                  : 'mdi-language-markdown-outline'
              "
            >
              <template #append>
                <v-btn
                  icon="mdi-close"
                  size="small"
                  variant="text"
                  :disabled="importing"
                  @click="removeEntry(entry.id)"
                />
              </template>
            </v-list-item>
          </v-list>
          <p
            v-if="hiddenEntryCount > 0"
            class="text-caption text-medium-emphasis mt-2"
          >
            仅预览前 100 个文件，另有 {{ hiddenEntryCount }} 个文件也会导入。
          </p>
        </div>

        <v-checkbox
          v-model="overwrite"
          label="覆盖知识库中路径相同的页面"
          color="primary"
          density="compact"
          hide-details
          :disabled="importing"
          class="mt-4"
        />

        <div v-if="importing" class="mt-4">
          <div class="text-caption text-medium-emphasis mb-2">
            {{ statusMessage }}
          </div>
          <v-progress-linear
            color="primary"
            :indeterminate="progress.total <= 0"
            :model-value="progressValue"
            rounded
          />
        </div>
      </v-card-text>

      <v-card-actions class="pa-4">
        <v-spacer />
        <v-btn variant="text" :disabled="importing" @click="close">取消</v-btn>
        <v-btn
          color="primary"
          variant="tonal"
          :loading="importing"
          :disabled="entries.length === 0"
          @click="submit"
        >
          开始导入
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<style scoped>
.import-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.file-preview {
  max-height: 320px;
  overflow-y: auto;
}
</style>
