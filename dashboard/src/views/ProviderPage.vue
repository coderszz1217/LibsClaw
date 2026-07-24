<template>
  <div class="provider-page">
    <v-container fluid class="provider-shell">
      <section class="provider-hero">
        <div class="provider-hero__copy">
          <h1 class="provider-hero__title">
            {{ tm('title') }}
          </h1>
          <p class="provider-hero__subtitle">
            {{ tm('subtitle') }}
          </p>
        </div>
        <v-btn
          v-if="selectedProviderType !== 'chat_completion'"
          color="primary"
          prepend-icon="mdi-plus"
          variant="flat"
          class="provider-hero__action"
          @click="showAddProviderDialog = true"
        >
          {{ tm('providers.addProvider') }}
        </v-btn>
      </section>

      <section class="provider-content">
        <v-tabs v-model="selectedProviderType" bg-color="transparent" class="mb-4">
          <v-tab
            v-for="type in providerTypes"
            :key="type.value"
            :value="type.value"
            class="font-weight-medium px-3"
          >
            <v-icon start>{{ type.icon }}</v-icon>
            {{ type.label }}
          </v-tab>
        </v-tabs>

        <div v-if="selectedProviderType === 'chat_completion'" class="provider-workbench">
          <div class="provider-workbench__sidebar">
            <ProviderSourcesPanel
              :displayed-provider-sources="displayedProviderSources"
              :selected-provider-source="selectedProviderSource"
              :available-source-types="availableSourceTypes"
              :tm="tm"
              :resolve-source-icon="resolveSourceIcon"
              :get-source-display-name="getSourceDisplayName"
              @add-provider-source="addProviderSource"
              @select-provider-source="selectProviderSource"
              @delete-provider-source="deleteProviderSource"
            />
          </div>

          <div class="provider-workbench__divider"></div>

          <div class="provider-workbench__main">
            <div v-if="selectedProviderSource" class="provider-config-shell">
              <div class="provider-config-header">
                <div class="provider-config-headline">
                  <div class="provider-config-title">{{ selectedProviderSource.id }}</div>
                  <div class="provider-config-subtitle">
                    {{ selectedProviderSource.api_base || 'N/A' }}
                  </div>
                </div>

                <div class="provider-config-actions">
                  <v-btn
                    color="primary"
                    prepend-icon="mdi-content-save-outline"
                    :loading="savingSource"
                    :disabled="!isSourceModified"
                    variant="flat"
                    class="provider-config-save"
                    @click="saveProviderSource"
                  >
                    {{ tm('providerSources.save') }}
                  </v-btn>
                </div>
              </div>

              <v-divider></v-divider>

              <div class="provider-config-body">
                <section class="provider-section">
                  <div class="provider-section-head">
                    <div class="provider-section-title">{{ tm('providers.settings') }}</div>
                  </div>
                  <AstrBotConfig
                    v-if="basicSourceConfig"
                    :iterable="basicSourceConfig"
                    :metadata="providerSourceSchema"
                    metadataKey="provider"
                    :is-editing="true"
                  />
                </section>

                <v-divider v-if="advancedSourceConfig"></v-divider>

                <section v-if="advancedSourceConfig" class="provider-section">
                  <div class="provider-section-head">
                    <div class="provider-section-title">{{ tm('providerSources.advancedConfig') }}</div>
                  </div>
                  <AstrBotConfig
                    :iterable="advancedSourceConfig"
                    :metadata="providerSourceSchema"
                    metadataKey="provider"
                    :is-editing="true"
                  />
                </section>

                <v-divider></v-divider>

                <section class="provider-section provider-section--models">
                  <ProviderModelsPanel
                    :entries="filteredMergedModelEntries"
                    :available-count="availableModels.length"
                    v-model:model-search="modelSearch"
                    :loading-models="loadingModels"
                    :is-source-modified="isSourceModified"
                    :supports-image-input="supportsImageInput"
                    :supports-audio-input="supportsAudioInput"
                    :supports-tool-call="supportsToolCall"
                    :supports-reasoning="supportsReasoning"
                    :format-context-limit="formatContextLimit"
                    :testing-providers="testingProviders"
                    :tm="tm"
                    @fetch-models="fetchAvailableModels"
                    @open-manual-model="openManualModelDialog"
                    @open-provider-edit="openProviderEdit"
                    @toggle-provider-enable="toggleProviderEnable"
                    @test-provider="testProvider"
                    @delete-provider="deleteProvider"
                    @add-model-provider="openModelAddDialog"
                  />
                </section>
              </div>
            </div>

            <div v-else class="provider-empty-state">
              <v-icon size="48" color="grey-lighten-1">mdi-cursor-default-click</v-icon>
              <p class="mt-2">{{ tm('providerSources.selectHint') }}</p>
            </div>
          </div>
        </div>

        <template v-else>
          <div v-if="filteredProviders.length === 0" class="provider-empty-state provider-empty-state--catalog">
            <v-icon size="46" color="primary">mdi-api-off</v-icon>
            <p>{{ getEmptyText() }}</p>
          </div>
          <div v-else class="provider-grid">
            <div v-for="(provider, index) in filteredProviders" :key="index" class="provider-card-shell">
              <item-card
                :item="provider"
                title-field="id"
                enabled-field="enable"
                :loading="isProviderTesting(provider.id)"
                :bglogo="getProviderIcon(provider.provider)"
                :show-copy-button="true"
                @toggle-enabled="toggleProviderEnable(provider, !provider.enable)"
                @delete="deleteProvider"
                @edit="configExistingProvider"
                @copy="copyProvider"
              >
                <template #item-details="{ item }">
                  <v-tooltip v-if="getProviderStatus(item.id)" location="top" max-width="300">
                    <template #activator="{ props }">
                      <v-chip v-bind="props" :color="getStatusColor(getProviderStatus(item.id).status)" size="small">
                        <v-icon start size="small">
                          {{
                            getProviderStatus(item.id).status === 'available'
                              ? 'mdi-check-circle'
                              : getProviderStatus(item.id).status === 'unavailable'
                                ? 'mdi-alert-circle'
                                : 'mdi-clock-outline'
                          }}
                        </v-icon>
                        {{ getStatusText(getProviderStatus(item.id).status) }}
                      </v-chip>
                    </template>
                    <span v-if="getProviderStatus(item.id).status === 'unavailable'">
                      {{ getProviderStatus(item.id).error }}
                    </span>
                    <span v-else>{{ getStatusText(getProviderStatus(item.id).status) }}</span>
                  </v-tooltip>
                </template>

                <template #actions="{ item }">
                  <v-btn
                    style="z-index: 100000;"
                    variant="tonal"
                    color="info"
                    size="small"
                    class="provider-card-action"
                    :loading="isProviderTesting(item.id)"
                    @click="testSingleProvider(item)"
                  >
                    {{ tm('availability.test') }}
                  </v-btn>
                </template>
              </item-card>
            </div>
          </div>
        </template>
      </section>
    </v-container>

    <AddNewProvider
      v-model:show="showAddProviderDialog"
      :metadata="configSchema"
      :current-provider-type="selectedProviderType"
      @select-template="selectProviderTemplate"
    />

    <v-dialog v-model="showManualModelDialog" max-width="400">
      <v-card>
        <v-card-title class="text-h3 pa-4 pb-0 pl-6">
          {{ tm('models.manualDialogTitle') }}
        </v-card-title>
        <v-card-text class="py-4">
          <v-text-field
            v-model="manualModelId"
            :label="tm('models.manualDialogModelLabel')"
            flat
            variant="solo-filled"
            autofocus
            clearable
          ></v-text-field>
          <v-text-field
            :model-value="manualProviderId"
            flat
            variant="solo-filled"
            :label="tm('models.manualDialogPreviewLabel')"
            persistent-hint
            :hint="tm('models.manualDialogPreviewHint')"
          ></v-text-field>
        </v-card-text>
        <v-card-actions class="pa-4">
          <v-spacer></v-spacer>
          <v-btn variant="text" @click="showManualModelDialog = false">取消</v-btn>
          <v-btn color="primary" variant="tonal" @click="confirmManualModel">添加</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="showProviderCfg" width="900" persistent>
      <v-card>
        <v-card-title class="text-h3 pa-4 pb-0 pl-6">
          {{ updatingMode ? tm('dialogs.config.editTitle') : tm('dialogs.config.addTitle') + ` ${newSelectedProviderName} ` + tm('dialogs.config.provider') }}
        </v-card-title>
        <v-card-text class="py-4">
          <AstrBotConfig
            :iterable="newSelectedProviderConfig"
            :metadata="configSchema"
            metadataKey="provider"
            :is-editing="updatingMode"
          />
        </v-card-text>

        <v-divider></v-divider>

        <v-card-actions class="pa-4">
          <v-spacer></v-spacer>
          <v-btn variant="text" :disabled="loading" @click="showProviderCfg = false">
            {{ tm('dialogs.config.cancel') }}
          </v-btn>
          <v-btn color="primary" variant="tonal" :loading="loading" @click="newProvider">
            {{ tm('dialogs.config.save') }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="showProviderEditDialog" width="800">
      <v-card>
        <v-card-title class="text-h3 pa-4 pb-0 pl-6">
          {{ providerEditDialogTitle }}
        </v-card-title>
        <v-card-text class="py-4">
          <AstrBotConfig
            v-if="providerEditData"
            :iterable="providerEditData"
            :metadata="providerModelConfigSchema"
            metadataKey="provider"
            :is-editing="true"
          />
        </v-card-text>
        <v-card-actions class="pa-4">
          <v-spacer></v-spacer>
          <v-btn
            variant="text"
            :disabled="savingProviders.includes(providerEditData?.id)"
            @click="showProviderEditDialog = false"
          >
            {{ tm('dialogs.config.cancel') }}
          </v-btn>
          <v-btn
            color="primary"
            variant="tonal"
            :loading="savingProviders.includes(providerEditData?.id)"
            @click="saveEditedProvider"
          >
            {{ tm('dialogs.config.save') }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snackbar.show" :color="snackbar.color" :timeout="3000" location="top">
      {{ snackbar.message }}
    </v-snackbar>

    <v-dialog v-model="showAgentRunnerDialog" max-width="520" persistent>
      <v-card>
        <v-card-title class="text-h3 pa-4 pb-0 pl-6 d-flex align-center">
          <v-icon start class="me-2">mdi-information</v-icon>
          请前往「配置文件」页测试 Agent 执行器
        </v-card-title>
        <v-card-text class="py-4 text-body-1 text-medium-emphasis">
          Agent 执行器的测试请在「配置文件」页进行。
          <ol class="ml-4 mt-4 mb-4">
            <li>找到对应的配置文件并打开。</li>
            <li>找到 Agent 执行方式部分，修改执行器后点击保存。</li>
            <li>点击右下角的 💬 聊天按钮进行测试。</li>
          </ol>
          要让机器人应用这个 Agent 执行器，你也需要前往修改 Agent 执行器。
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn color="grey" variant="text" @click="showAgentRunnerDialog = false">好的</v-btn>
          <v-btn color="primary" variant="tonal" @click="goToConfigPage">点击前往</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { providerApi } from '@/api/v1'
import { useModuleI18n } from '@/i18n/composables'
import AstrBotConfig from '@/components/shared/AstrBotConfig.vue'
import ItemCard from '@/components/shared/ItemCard.vue'
import AddNewProvider from '@/components/provider/AddNewProvider.vue'
import ProviderModelsPanel from '@/components/provider/ProviderModelsPanel.vue'
import ProviderSourcesPanel from '@/components/provider/ProviderSourcesPanel.vue'
import { useProviderModelConfigDialog } from '@/composables/useProviderModelConfigDialog'
import { useProviderSources } from '@/composables/useProviderSources'
import { getProviderIcon } from '@/utils/providerUtils'

const props = defineProps({
  defaultTab: {
    type: String,
    default: 'chat_completion'
  }
})

const { tm } = useModuleI18n('features/provider')
const router = useRouter()

const snackbar = ref({
  show: false,
  message: '',
  color: 'success'
})

function showMessage(message, color = 'success') {
  snackbar.value = { show: true, message, color }
}

const {
  providers,
  selectedProviderType,
  selectedProviderSource,
  availableModels,
  loadingModels,
  savingSource,
  testingProviders,
  isSourceModified,
  configSchema,
  providerSourceSchema,
  manualModelId,
  modelSearch,
  providerTypes,
  availableSourceTypes,
  displayedProviderSources,
  filteredMergedModelEntries,
  filteredProviders,
  basicSourceConfig,
  advancedSourceConfig,
  manualProviderId,
  resolveSourceIcon,
  getSourceDisplayName,
  supportsImageInput,
  supportsAudioInput,
  supportsToolCall,
  supportsReasoning,
  formatContextLimit,
  updateDefaultTab,
  selectProviderSource,
  addProviderSource,
  deleteProviderSource,
  saveProviderSource,
  fetchAvailableModels,
  buildModelProviderConfig,
  deleteProvider,
  modelAlreadyConfigured,
  testProvider,
  loadConfig
} = useProviderSources({
  defaultTab: props.defaultTab,
  tm,
  showMessage
})

const showAddProviderDialog = ref(false)
const showProviderCfg = ref(false)
const newSelectedProviderName = ref('')
const newSelectedProviderConfig = ref({})
const newProviderOriginalId = ref('')
const updatingMode = ref(false)
const loading = ref(false)
const providerStatuses = ref([])
const showAgentRunnerDialog = ref(false)
const showManualModelDialog = ref(false)

const {
  showProviderEditDialog,
  providerEditData,
  savingProviders,
  providerModelConfigSchema,
  providerEditDialogTitle,
  openProviderEdit,
  openModelAddDialog,
  saveEditedProvider
} = useProviderModelConfigDialog({
  selectedProviderSource,
  configSchema,
  buildModelProviderConfig,
  modelAlreadyConfigured,
  loadConfig,
  tm,
  showMessage
})

function openManualModelDialog() {
  if (!selectedProviderSource.value) {
    showMessage(tm('providerSources.selectHint'), 'error')
    return
  }
  manualModelId.value = ''
  showManualModelDialog.value = true
}

async function confirmManualModel() {
  const modelId = manualModelId.value.trim()
  if (!selectedProviderSource.value) {
    showMessage(tm('providerSources.selectHint'), 'error')
    return
  }
  if (!modelId) {
    showMessage(tm('models.manualModelRequired'), 'error')
    return
  }
  if (modelAlreadyConfigured(modelId)) {
    showMessage(tm('models.manualModelExists'), 'error')
    return
  }
  showManualModelDialog.value = false
  openModelAddDialog(modelId)
}

watch(() => props.defaultTab, (val) => {
  updateDefaultTab(val)
})

function getEmptyText() {
  return tm('providers.empty.typed', { type: selectedProviderType.value })
}

function selectProviderTemplate(name) {
  newSelectedProviderName.value = name
  newProviderOriginalId.value = ''
  showProviderCfg.value = true
  updatingMode.value = false
  newSelectedProviderConfig.value = JSON.parse(JSON.stringify(
    configSchema.value.provider.config_template[name] || {}
  ))
}

function configExistingProvider(provider) {
  newSelectedProviderName.value = provider.id
  newProviderOriginalId.value = provider.id
  newSelectedProviderConfig.value = {}

  let templates = configSchema.value.provider.config_template || {}
  let defaultConfig = {}
  for (let key in templates) {
    if (templates[key]?.type === provider.type) {
      defaultConfig = templates[key]
      break
    }
  }

  const mergeConfigWithOrder = (target, source, reference) => {
    if (source && typeof source === 'object' && !Array.isArray(source)) {
      for (let key in source) {
        if (source.hasOwnProperty(key)) {
          if (typeof source[key] === 'object' && source[key] !== null) {
            target[key] = Array.isArray(source[key]) ? [...source[key]] : { ...source[key] }
          } else {
            target[key] = source[key]
          }
        }
      }
    }

    for (let key in reference) {
      if (typeof reference[key] === 'object' && reference[key] !== null) {
        if (!(key in target)) {
          if (Array.isArray(reference[key])) {
            target[key] = [...reference[key]]
          } else {
            target[key] = {}
          }
        }
        if (!Array.isArray(reference[key])) {
          mergeConfigWithOrder(
            target[key],
            source && source[key] ? source[key] : {},
            reference[key]
          )
        }
      } else if (!(key in target)) {
        target[key] = reference[key]
      }
    }
  }

  if (defaultConfig) {
    mergeConfigWithOrder(newSelectedProviderConfig.value, provider, defaultConfig)
  }

  showProviderCfg.value = true
  updatingMode.value = true
}

async function newProvider() {
  loading.value = true
  const wasUpdating = updatingMode.value
  try {
    if (wasUpdating) {
      const res = await providerApi.update(
        newProviderOriginalId.value || newSelectedProviderName.value,
        newSelectedProviderConfig.value
      )
      if (res.data.status === 'error') {
        showMessage(res.data.message || '更新失败!', 'error')
        return
      }
      showMessage(res.data.message || '更新成功!')
      if (wasUpdating) {
        updatingMode.value = false
      }
    } else {
      const res = await providerApi.create(newSelectedProviderConfig.value)
      if (res.data.status === 'error') {
        showMessage(res.data.message || '添加失败!', 'error')
        return
      }
      showMessage(res.data.message || '添加成功!')
    }
    showProviderCfg.value = false
  } catch (err) {
    showMessage(err.response?.data?.message || err.message, 'error')
  } finally {
    loading.value = false
    await loadConfig()
  }
}

async function copyProvider(providerToCopy) {
  const newProviderConfig = JSON.parse(JSON.stringify(providerToCopy))

  const generateUniqueId = (baseId) => {
    let newId = `${baseId}_copy`
    let counter = 1
    const existingIds = providers.value.map(p => p.id)
    while (existingIds.includes(newId)) {
      newId = `${baseId}_copy_${counter}`
      counter++
    }
    return newId
  }
  newProviderConfig.id = generateUniqueId(providerToCopy.id)
  newProviderConfig.enable = false

  loading.value = true
  try {
    const res = await providerApi.create(newProviderConfig)
    showMessage(res.data.message || `成功复制并创建了 ${newProviderConfig.id}`)
    await loadConfig()
  } catch (err) {
    showMessage(err.response?.data?.message || err.message, 'error')
  } finally {
    loading.value = false
  }
}

async function toggleProviderEnable(provider, value) {
  provider.enable = value

  try {
    const res = await providerApi.setEnabled(provider.id, { enabled: value })

    if (res.data.status === 'error') {
      throw new Error(res.data.message)
    }
    showMessage(res.data.message || tm('messages.success.statusUpdate'))
  } catch (error) {
    showMessage(error.response?.data?.message || error.message || tm('providerSources.saveError'), 'error')
  } finally {
    await loadConfig()
  }
}

function isProviderTesting(providerId) {
  return testingProviders.value.includes(providerId)
}

function getProviderStatus(providerId) {
  return providerStatuses.value.find(s => s.id === providerId)
}

async function testSingleProvider(provider) {
  if (isProviderTesting(provider.id)) return

  testingProviders.value.push(provider.id)

  const statusIndex = providerStatuses.value.findIndex(s => s.id === provider.id)
  const pendingStatus = {
    id: provider.id,
    name: provider.id,
    status: 'pending',
    error: null
  }
  if (statusIndex !== -1) {
    providerStatuses.value.splice(statusIndex, 1, pendingStatus)
  } else {
    providerStatuses.value.unshift(pendingStatus)
  }

  try {
    if (!provider.enable) {
      throw new Error('该提供商未被用户启用')
    }
    if (provider.provider_type === 'agent_runner') {
      showAgentRunnerDialog.value = true
      providerStatuses.value = providerStatuses.value.filter(s => s.id !== provider.id)
      return
    }

    const startTime = performance.now()
    const res = await providerApi.test(provider.id)
    if (!res.data || res.data.status !== 'ok') {
      throw new Error(res.data?.message || `Failed to check status for ${provider.id}`)
    }

    const result = res.data.data
    if (!result) {
      throw new Error(`Failed to check status for ${provider.id}`)
    }

    const index = providerStatuses.value.findIndex(s => s.id === provider.id)
    if (index !== -1) {
      providerStatuses.value.splice(index, 1, result)
    }

    const isAvailable = result.status === 'available' && result.error == null
    if (!isAvailable) {
      throw new Error(result.error || tm('models.testError'))
    }

    const latency = Math.max(0, Math.round(performance.now() - startTime))
    showMessage(tm('models.testSuccessWithLatency', { id: provider.id, latency }))
  } catch (err) {
    const errorMessage = err.response?.data?.message || err.message || tm('models.testError')
    const index = providerStatuses.value.findIndex(s => s.id === provider.id)
    const failedStatus = {
      id: provider.id,
      name: provider.id,
      status: 'unavailable',
      error: errorMessage
    }
    if (index !== -1) {
      providerStatuses.value.splice(index, 1, failedStatus)
    }
    showMessage(errorMessage, 'error')
  } finally {
    const index = testingProviders.value.indexOf(provider.id)
    if (index > -1) {
      testingProviders.value.splice(index, 1)
    }
  }
}

function getStatusColor(status) {
  switch (status) {
    case 'available':
      return 'success'
    case 'unavailable':
      return 'error'
    case 'pending':
      return 'grey'
    default:
      return 'default'
  }
}

function getStatusText(status) {
  const messages = {
    available: tm('availability.available'),
    unavailable: tm('availability.unavailable'),
    pending: tm('availability.pending')
  }
  return messages[status] || status
}

function goToConfigPage() {
  router.push('/config')
  showAgentRunnerDialog.value = false
}
</script>

<style scoped>
.provider-page {
  --provider-surface: rgb(var(--v-theme-surface));
  --provider-border: rgba(var(--v-theme-border), 0.7);
  min-height: 100%;
  background:
    linear-gradient(180deg, rgba(var(--v-theme-primary), 0.08), transparent 280px),
    rgb(var(--v-theme-background));
}

.provider-shell {
  max-width: 1200px;
  padding: 24px;
}

.provider-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
  padding: 18px 2px 20px;
  border: 1px solid var(--provider-border);
  border-width: 0 0 1px;
}

.provider-hero__copy {
  min-width: 0;
}

.provider-hero__title {
  margin: 0;
  color: rgb(var(--v-theme-primaryText));
  font-size: 1.65rem;
  font-weight: 730;
  line-height: 1.25;
  letter-spacing: 0;
}

.provider-hero__subtitle {
  margin: 6px 0 0;
  color: rgba(var(--v-theme-on-surface), 0.68);
  font-size: 0.9rem;
  line-height: 1.55;
}

.provider-hero__action,
.provider-config-save {
  height: 46px;
  max-height: 46px;
  flex: 0 0 auto;
  padding: 0 18px;
  border-radius: 8px;
  box-shadow: 0 8px 18px rgba(var(--v-theme-primary), 0.18);
}

.provider-content :deep(.v-tabs) {
  min-height: 52px;
  border: 1px solid rgba(var(--v-theme-border), 0.7);
  border-radius: 12px;
  background: rgba(var(--v-theme-surface), 0.78);
  padding: 3px;
}

.provider-content :deep(.v-tab) {
  min-height: 38px;
  border-radius: 8px;
  letter-spacing: 0;
}

.provider-content :deep(.v-tab--selected) {
  background: rgba(var(--v-theme-primary), 0.1);
}

.provider-workbench {
  border: 1px solid var(--provider-border);
  border-radius: 18px;
  background: rgba(var(--v-theme-surface), 0.96);
  box-shadow: 0 18px 48px rgba(17, 24, 39, 0.08);
  display: grid;
  grid-template-columns: minmax(280px, 320px) 1px minmax(0, 1fr);
  min-height: 720px;
  overflow: hidden;
}

.provider-workbench__sidebar,
.provider-workbench__main {
  min-width: 0;
}

.provider-workbench__divider {
  background: rgba(var(--v-theme-border), 0.7);
}

.provider-workbench__main {
  display: flex;
}

.provider-config-shell {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.provider-config-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 18px 22px 16px;
  background: rgba(var(--v-theme-surface), 0.94);
}

.provider-config-headline {
  min-width: 0;
}

.provider-config-title {
  font-size: 20px;
  line-height: 1.1;
  font-weight: 680;
  letter-spacing: 0;
  overflow-wrap: anywhere;
}

.provider-config-subtitle {
  margin-top: 6px;
  color: rgba(var(--v-theme-on-surface), 0.62);
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.provider-config-actions {
  flex-shrink: 0;
}

.provider-config-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.provider-section {
  padding: 18px 22px;
}

.provider-section--models {
  padding-top: 16px;
}

.provider-section-head {
  margin-bottom: 10px;
}

.provider-section-title {
  font-size: 16px;
  font-weight: 650;
  line-height: 1.4;
  letter-spacing: 0;
}

.provider-empty-state {
  flex: 1;
  min-height: 360px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: rgba(var(--v-theme-on-surface), 0.56);
}

.provider-empty-state p {
  margin: 0;
  font-size: 14px;
}

.provider-empty-state--catalog {
  min-height: 260px;
  border: 1px dashed rgba(var(--v-theme-on-surface), 0.16);
  border-radius: 18px;
  background: rgba(var(--v-theme-surface), 0.84);
  box-shadow: 0 18px 48px rgba(17, 24, 39, 0.05);
}

.provider-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 18px;
}

.provider-card-shell {
  min-width: 0;
}

.provider-card-shell :deep(.v-card),
.provider-card-shell :deep(.item-card) {
  border-color: rgba(var(--v-theme-border), 0.7) !important;
  border-radius: 16px !important;
  background: rgba(var(--v-theme-surface), 0.96) !important;
  box-shadow: 0 18px 48px rgba(17, 24, 39, 0.08) !important;
}

.provider-card-shell :deep(.v-card-title),
.provider-card-shell :deep(.text-h3),
.provider-card-shell :deep(.text-h4) {
  letter-spacing: 0 !important;
}

.provider-card-action {
  border-radius: 8px;
}

@media (max-width: 960px) {
  .provider-shell {
    padding: 16px;
  }

  .provider-hero {
    align-items: stretch;
    flex-direction: column;
    min-height: auto;
    padding: 10px 0 16px;
  }

  .provider-hero__action {
    width: 100%;
  }

  .provider-workbench {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1px auto;
    min-height: auto;
  }

  .provider-workbench__divider {
    height: 1px;
  }

  .provider-config-header {
    flex-direction: column;
    align-items: stretch;
    padding: 16px;
  }

  .provider-config-actions :deep(.v-btn) {
    width: 100%;
  }

  .provider-section {
    padding: 16px;
  }
}

@media (max-width: 600px) {
  .provider-shell {
    padding: 8px;
  }

  .provider-content :deep(.v-tabs) {
    overflow-x: auto;
  }

  .provider-workbench {
    border-radius: 16px;
    overflow: visible;
  }

  .provider-workbench__main {
    overflow: visible;
  }

  .provider-config-body {
    overflow-y: visible;
  }

  .provider-config-title {
    font-size: 18px;
  }

  .provider-empty-state {
    min-height: 260px;
    padding: 24px;
  }

  .provider-grid {
    grid-template-columns: 1fr;
  }
}
</style>
