<script setup>
import ConsoleDisplayer from '@/components/shared/ConsoleDisplayer.vue';
import { useModuleI18n } from '@/i18n/composables';
import { updatesApi } from '@/api/v1';
import { useToast } from '@/utils/toast';

const { tm } = useModuleI18n('features/console');
</script>

<template>
  <div class="console-page">
    <div class="console-header">
      <div class="console-title-block">
        <div class="console-title-line">
          <h1 class="console-title">{{ tm('title') }}</h1>
          <v-chip size="small" variant="tonal" color="primary" class="console-title-chip">
            {{ tm('streamLabel') }}
          </v-chip>
        </div>
        <p class="console-subtitle">
          {{ tm('debugHint.text') }}
        </p>
      </div>
      <div class="console-header-actions">
        <div class="console-autoscroll-card">
          <v-switch
            v-model="autoScrollEnabled"
            hide-details
            density="compact"
            inset
            color="primary"
          ></v-switch>
          <span>{{ autoScrollEnabled ? tm('autoScroll.enabled') : tm('autoScroll.disabled') }}</span>
        </div>
        <v-dialog v-model="pipDialog" width="400">
          <template v-slot:activator="{ props }">
            <v-btn class="console-pip-btn" variant="tonal" color="primary" prepend-icon="mdi-package-variant-plus" v-bind="props">
              {{ tm('pipInstall.button') }}
            </v-btn>
          </template>
          <v-card class="console-pip-dialog">
            <v-card-title class="text-h3 pa-4 pb-0 pl-6 console-pip-dialog-title">
              <span class="console-pip-dialog-icon">
                <v-icon size="18">mdi-package-variant</v-icon>
              </span>
              <span>{{ tm('pipInstall.dialogTitle') }}</span>
            </v-card-title>
            <v-card-text class="console-pip-dialog-body">
              <v-text-field v-model="pipInstallPayload.package" :label="tm('pipInstall.packageLabel')" variant="outlined"></v-text-field>
              <v-text-field v-model="pipInstallPayload.mirror" :label="tm('pipInstall.mirrorLabel')" variant="outlined"></v-text-field>
              <small class="console-pip-hint">{{ tm('pipInstall.mirrorHint') }}</small>
            </v-card-text>
            <v-card-actions class="console-pip-dialog-actions">
              <v-spacer></v-spacer>
              <v-btn class="console-pip-install-btn" color="primary" variant="tonal" @click="pipInstall" :loading="loading">
                {{ tm('pipInstall.installButton') }}
              </v-btn>
            </v-card-actions>
          </v-card>
        </v-dialog>
      </div>
    </div>
    <ConsoleDisplayer ref="consoleDisplayer" class="console-display" />
  </div>
</template>
<script>
export default {
  name: 'ConsolePage',
  components: {
    ConsoleDisplayer
  },
  data() {
    return {
      autoScrollEnabled: localStorage.getItem('console_auto_scroll') !== 'false',
      pipDialog: false,
      pipInstallPayload: {
        package: '',
        mirror: ''
      },
      loading: false
    }
  },
  mounted() {
    if (this.$refs.consoleDisplayer) {
      this.$refs.consoleDisplayer.autoScroll = this.autoScrollEnabled;
    }
  },
  watch: {
    autoScrollEnabled(val) {
      localStorage.setItem('console_auto_scroll', val);
      if (this.$refs.consoleDisplayer) {
        this.$refs.consoleDisplayer.autoScroll = val;
      }
    }
  },
  methods: {
    pipInstall() {
      const toast = useToast();
      this.loading = true;
      updatesApi.installPip(this.pipInstallPayload)
        .then(res => {
          if (res.data.status === 'ok') {
            toast.success(res.data.message || tm('pipInstall.installSuccess'));
            this.pipDialog = false;
          } else {
            toast.error(res.data.message || tm('pipInstall.installFailed'));
          }
        })
        .catch(err => {
          toast.error(err.response?.data?.message || tm('pipInstall.requestFailed'));
        }).finally(() => {
          this.loading = false;
        });
    }
  }
}

</script>

<style scoped>
.console-page {
  min-height: 100%;
  margin: 0 auto;
  max-width: 1480px;
  padding: 24px 28px 32px;
  width: 100%;
  background:
    linear-gradient(180deg, rgba(239, 248, 254, 0.72) 0%, rgba(255, 255, 255, 0) 260px),
    rgb(var(--v-theme-background));
}

.console-header {
  align-items: center;
  display: flex;
  gap: 18px;
  justify-content: space-between;
  margin-bottom: 16px;
  padding: 0 2px 14px;
  border-bottom: 1px solid rgba(var(--v-theme-border), 0.54);
}

.console-title-block {
  min-width: 0;
}

.console-title-line {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.console-title {
  margin: 0;
  color: rgb(var(--v-theme-primaryText));
  font-size: 21px;
  font-weight: 720;
  letter-spacing: 0;
  line-height: 1.25;
}

.console-title-chip {
  border-radius: 999px !important;
  background: rgba(var(--v-theme-primary), 0.09) !important;
  font-weight: 650;
}

.console-subtitle {
  margin: 7px 0 0;
  color: rgba(var(--v-theme-on-surface), 0.66);
  font-size: 13px;
  line-height: 1.6;
}

.console-header-actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.console-autoscroll-card {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  padding: 3px 12px 3px 6px;
  border: 1px solid rgba(42, 143, 204, 0.14);
  border-radius: 999px;
  background: #ffffff;
  color: rgba(var(--v-theme-on-surface), 0.78);
  font-size: 13px;
  font-weight: 650;
}

.console-pip-btn,
.console-pip-install-btn {
  height: 38px;
  border: 1px solid rgba(42, 143, 204, 0.18);
  border-radius: 11px !important;
  background: linear-gradient(180deg, #eaf6fd 0%, #dceff9 100%) !important;
  color: #1674a8 !important;
  font-weight: 720;
  letter-spacing: 0;
  box-shadow: none !important;
}

.console-display {
  height: calc(100vh - 185px);
  width: 100%;
}

.console-pip-dialog {
  overflow: hidden;
  border: 1px solid rgba(42, 143, 204, 0.12);
  border-radius: 18px !important;
  background: linear-gradient(180deg, #fbfdff 0%, #f7fbfe 100%) !important;
}

.console-pip-dialog-title {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 20px !important;
  color: #142433;
  font-size: 20px !important;
  font-weight: 800 !important;
  letter-spacing: 0;
}

.console-pip-dialog-icon {
  display: inline-grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 12px;
  background: #e8f5fc;
  color: #1d86bf;
}

.console-pip-dialog-body {
  padding: 18px 22px 10px !important;
}

.console-pip-hint {
  display: block;
  margin-top: -4px;
  color: rgba(var(--v-theme-on-surface), 0.58);
  line-height: 1.5;
}

.console-pip-dialog-actions {
  padding: 14px 22px 18px !important;
  border-top: 1px solid rgba(var(--v-theme-border), 0.36);
  background: rgba(248, 251, 253, 0.88);
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}

.fade-in {
  animation: fadeIn 0.2s ease-in-out;
}

@media (max-width: 768px) {
  .console-page {
    padding: 16px;
  }

  .console-header {
    align-items: flex-start;
    flex-direction: column;
    gap: 12px;
  }

  .console-header-actions {
    justify-content: flex-start;
    width: 100%;
  }

  .console-display {
    height: calc(100vh - 240px);
  }
}
</style>
