import { useEffect, useRef, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AppShell, type AppTab } from "@/components/layout/app-shell";
import { AdminModal } from "@/features/admin/admin-modal";
import { AuthPage } from "@/features/auth/auth-page";
import { ConfigPanel } from "@/features/config/config-panel";
import { ConfigTransfer } from "@/features/config/config-transfer";
import { Dashboard } from "@/features/dashboard/dashboard";
import { DiagnosticsPanel } from "@/features/diagnostics/diagnostics-panel";
import { UpdateModal } from "@/features/update/update-modal";
import { Button } from "@/components/ui/button";
import { api, type SavedSiteConfigSummary, type SavedSiteConfigDetail, type ConfigBundle } from "@/lib/api";

function hasUpdateAvailable(installedCommit: string | null | undefined, latestCommit: string | null | undefined, flag?: boolean | null) {
  return Boolean(flag || (installedCommit && latestCommit && installedCommit !== latestCommit));
}

export default function App() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<AppTab>("control");
  const [isAdminOpen, setIsAdminOpen] = useState(false);
  const [isUpdateOpen, setIsUpdateOpen] = useState(false);
  const [serviceActionError, setServiceActionError] = useState<string | null>(null);
  const [adminError, setAdminError] = useState<string | null>(null);
  const [updatePollError, setUpdatePollError] = useState<string | null>(null);
  const [updatePollingActive, setUpdatePollingActive] = useState(false);
  const autoCheckedRef = useRef(false);

  const bootstrapStatusQuery = useQuery({
    queryKey: ["bootstrap-status"],
    queryFn: api.getBootstrapStatus,
  });

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: api.getMe,
    retry: false,
  });

  const isAuthenticated = meQuery.data?.authenticated === true && Boolean(meQuery.data.user);

  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: api.getConfig,
    enabled: isAuthenticated,
  });

  const savedConfigsQuery = useQuery({
    queryKey: ["saved-site-configs"],
    queryFn: api.listSavedSiteConfigs,
    enabled: isAuthenticated,
  });

  const savedInputsQuery = useQuery({
    queryKey: ["saved-inputs"],
    queryFn: api.listSavedInputs,
    enabled: isAuthenticated,
  });

  const savedDestinationsQuery = useQuery({
    queryKey: ["saved-destinations"],
    queryFn: api.listSavedDestinations,
    enabled: isAuthenticated,
  });

  const statusQuery = useQuery({
    queryKey: ["service-status"],
    queryFn: api.getServiceStatus,
    enabled: isAuthenticated,
    refetchInterval: 2000,
    retry: 1,
  });

  const diagnosticsQuery = useQuery({
    queryKey: ["diagnostics"],
    queryFn: api.getDiagnostics,
    enabled: isAuthenticated,
  });

  const logsQuery = useQuery({
    queryKey: ["logs"],
    queryFn: api.getLogs,
    enabled: isAuthenticated,
  });

  const systemQuery = useQuery({
    queryKey: ["system"],
    queryFn: api.getSystemInfo,
    enabled: isAuthenticated,
  });

  const redundancyQuery = useQuery({
    queryKey: ["redundancy-status"],
    queryFn: api.getRedundancyStatus,
    enabled: isAuthenticated,
  });

  const usersQuery = useQuery({
    queryKey: ["users"],
    queryFn: api.getUsers,
    enabled: isAuthenticated && meQuery.data?.user?.role === "owner" && isAdminOpen,
  });

  const isOwner = isAuthenticated && meQuery.data?.user?.role === "owner";

  const updateStatusQuery = useQuery({
    queryKey: ["update-status"],
    queryFn: api.getUpdateStatus,
    enabled: isOwner,
  });

  const updateJobQuery = useQuery({
    queryKey: ["update-job"],
    queryFn: api.getUpdateJob,
    enabled:
      isOwner &&
      (isUpdateOpen ||
        updatePollingActive ||
        updateStatusQuery.data?.job_status === "failed" ||
        updateStatusQuery.data?.job_status === "rolled_back"),
    refetchInterval: updatePollingActive ? 3000 : false,
    retry: false,
  });

  const loginMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) => api.login(username, password),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      await queryClient.invalidateQueries({ queryKey: ["bootstrap-status"] });
    },
  });

  const bootstrapMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) => api.bootstrapOwner(username, password),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      await queryClient.invalidateQueries({ queryKey: ["bootstrap-status"] });
    },
  });

  const logoutMutation = useMutation({
    mutationFn: api.logout,
    onSuccess: async () => {
      queryClient.clear();
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      await queryClient.invalidateQueries({ queryKey: ["bootstrap-status"] });
    },
  });

  const serviceMutation = useMutation({
    mutationFn: ({ action, expectedSelectionId }: { action: "start" | "stop" | "restart"; expectedSelectionId?: string }) =>
      api.runServiceAction(action, expectedSelectionId),
    onMutate: () => {
      setServiceActionError(null);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["service-status"] });
      await queryClient.invalidateQueries({ queryKey: ["logs"] });
      await queryClient.invalidateQueries({ queryKey: ["diagnostics"] });
    },
    onError: async (error) => {
      setServiceActionError(error instanceof Error ? error.message : "Service action failed");
      await queryClient.invalidateQueries({ queryKey: ["service-status"] });
      await queryClient.invalidateQueries({ queryKey: ["diagnostics"] });
    },
  });

  const saveConfigMutation = useMutation({
    mutationFn: async ({ name, site, base }: { name: string; site: ConfigBundle["site"]; base?: SavedSiteConfigSummary }) => {
      const saved = await api.saveNamedSiteConfig(name, site, base);
      return api.openSavedSiteConfig(saved.saved_config.id, saved.saved_config.revision);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["saved-site-configs"] }),
  });

  const applyConfigMutation = useMutation({
    mutationFn: ({ review, requestId }: { review: SavedSiteConfigDetail; requestId: string }) => api.applySavedSiteConfig(review, requestId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["config"] });
      await queryClient.invalidateQueries({ queryKey: ["service-status"] });
      await queryClient.invalidateQueries({ queryKey: ["diagnostics"] });
    },
  });

  const renameSavedConfigMutation = useMutation({
    mutationFn: ({ preset, name }: { preset: SavedSiteConfigSummary; name: string }) => api.renameSavedSiteConfig(preset, name),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["saved-site-configs"] }),
  });

  const deleteSavedConfigMutation = useMutation({
    mutationFn: api.deleteSavedSiteConfig,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["saved-site-configs"] }),
  });

  const saveInputMutation = useMutation({
    mutationFn: api.saveInput,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["saved-inputs"] });
    },
  });

  const saveDestinationMutation = useMutation({
    mutationFn: api.saveDestination,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["saved-destinations"] });
    },
  });

  const createUserMutation = useMutation({
    mutationFn: api.createUser,
    onMutate: () => {
      setAdminError(null);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (error) => {
      setAdminError(error instanceof Error ? error.message : "Unable to create user");
    },
  });

  const updateUserMutation = useMutation({
    mutationFn: ({ userId, payload }: { userId: string; payload: Parameters<typeof api.updateUser>[1] }) => api.updateUser(userId, payload),
    onMutate: () => {
      setAdminError(null);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["users"] });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    onError: (error) => {
      setAdminError(error instanceof Error ? error.message : "Unable to update user");
    },
  });

  const checkUpdateMutation = useMutation({
    mutationFn: api.checkForUpdates,
    onMutate: () => {
      setUpdatePollError(null);
    },
    onSuccess: async (data) => {
      queryClient.setQueryData(["update-status"], data);
      await queryClient.invalidateQueries({ queryKey: ["update-job"] });
    },
    onError: (error) => {
      setUpdatePollError(error instanceof Error ? error.message : "Unable to check for updates");
    },
  });

  const installUpdateMutation = useMutation({
    mutationFn: api.launchUpdater,
    onMutate: () => {
      setUpdatePollError(null);
    },
    onSuccess: async (data) => {
      window.location.assign(data.updater_url);
    },
    onError: (error) => {
      setUpdatePollError(error instanceof Error ? error.message : "Unable to open updater");
    },
  });

  useEffect(() => {
    if (!isOwner || autoCheckedRef.current) {
      return;
    }
    autoCheckedRef.current = true;
    void checkUpdateMutation.mutateAsync();
  }, [checkUpdateMutation, isOwner]);

  useEffect(() => {
    const running = updateStatusQuery.data?.job_status === "running" || updateJobQuery.data?.job_status === "running";
    if (running && !updatePollingActive) {
      setUpdatePollingActive(true);
    }
  }, [updateJobQuery.data?.job_status, updatePollingActive, updateStatusQuery.data?.job_status]);

  useEffect(() => {
    if (updateJobQuery.error && updateStatusQuery.data?.job_status === "running") {
      setUpdatePollError("Reconnecting to the control plane while services restart...");
      return;
    }
    if (updateJobQuery.error) {
      setUpdatePollError(updateJobQuery.error instanceof Error ? updateJobQuery.error.message : "Unable to read update progress");
      return;
    }
    if (updateJobQuery.data?.job_status && updateJobQuery.data.job_status !== "running") {
      setUpdatePollingActive(false);
      void queryClient.invalidateQueries({ queryKey: ["update-status"] });
    }
  }, [queryClient, updateJobQuery.data, updateJobQuery.error, updateStatusQuery.data?.job_status]);

  const updateAvailable = hasUpdateAvailable(
    updateStatusQuery.data?.installed_commit,
    updateStatusQuery.data?.latest_commit,
    updateStatusQuery.data?.update_available,
  );

  const updateNotice = isOwner && updateStatusQuery.data
    ? updateStatusQuery.data.job_status === "running"
      ? { label: "Updating...", tone: "running" as const }
      : updateStatusQuery.data.job_status === "failed" || updateStatusQuery.data.job_status === "rolled_back"
        ? { label: "Update issue", tone: "failed" as const }
        : updateAvailable
          ? { label: "Update available", tone: "available" as const }
          : { label: "Updates", tone: "running" as const }
    : undefined;

  if (bootstrapStatusQuery.isLoading || meQuery.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <div className="glass-panel flex w-full max-w-md items-center gap-4 rounded-[28px] px-6 py-5 text-sm text-slate-200">
          <span className="h-3 w-3 animate-pulse rounded-full bg-[var(--accent-strong)]" />
          Connecting to controller...
        </div>
      </div>
    );
  }

  if (!isAuthenticated || !meQuery.data?.user) {
    return (
      <AuthPage
        hasOwner={!(bootstrapStatusQuery.data?.requires_bootstrap ?? false)}
        onLogin={(username, password) => loginMutation.mutateAsync({ username, password }).then(() => undefined)}
        onBootstrap={(username, password) => bootstrapMutation.mutateAsync({ username, password }).then(() => undefined)}
      />
    );
  }

  return (
    <>
      <AppShell
        user={meQuery.data.user}
        hostname={systemQuery.data?.hostname}
        onLogout={() => void logoutMutation.mutateAsync()}
        onOpenAdmin={() => {
          setAdminError(null);
          setIsAdminOpen(true);
        }}
        updateNotice={updateNotice}
        onOpenUpdates={isOwner ? () => setIsUpdateOpen(true) : undefined}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      >
        {activeTab === "control" && configQuery.isError ? (
          <section className="space-y-4 rounded-3xl border border-amber-300/20 p-6">
            <p>Selected configuration is unavailable. Stop remains available while the sender is active.</p>
            <Button disabled={serviceMutation.isPending || !statusQuery.data?.allowed_actions.includes("stop")} onClick={() => {
              void serviceMutation.mutateAsync({ action: "stop" }).catch(() => undefined);
            }}>Stop</Button>
            {serviceActionError ? <p>{serviceActionError}</p> : null}
          </section>
        ) : null}
        {activeTab === "control" && configQuery.data ? (
          <Dashboard
            config={configQuery.data}
            status={statusQuery.data}
            statusUnavailable={statusQuery.isError}
            statusUpdatedAt={statusQuery.dataUpdatedAt}
            redundancy={redundancyQuery.data}
            onAction={(action, expectedSelectionId) => serviceMutation.mutateAsync({ action, expectedSelectionId }).then(() => undefined)}
            actionError={serviceActionError}
            isActionPending={serviceMutation.isPending}
          />
        ) : null}
        {configQuery.data ? (
          <div hidden={activeTab !== "config"} className="space-y-6">
          {meQuery.data.user.role !== "operator" && <ConfigTransfer onImported={async () => {
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: ["saved-site-configs"] }),
              queryClient.invalidateQueries({ queryKey: ["saved-inputs"] }),
              queryClient.invalidateQueries({ queryKey: ["saved-destinations"] }),
            ]);
          }} />}
          <ConfigPanel
            config={configQuery.data}
            savedConfigs={savedConfigsQuery.data}
            savedInputs={savedInputsQuery.data}
            savedDestinations={savedDestinationsQuery.data}
            isLoadingSavedConfigs={savedConfigsQuery.isLoading}
            isMutatingSavedConfigs={
              saveConfigMutation.isPending ||
              applyConfigMutation.isPending ||
              renameSavedConfigMutation.isPending ||
              deleteSavedConfigMutation.isPending ||
              saveInputMutation.isPending ||
              saveDestinationMutation.isPending
            }
            onSave={(name, site, base) => saveConfigMutation.mutateAsync({ name, site, base })}
            onLoadSaved={api.openSavedSiteConfig}
            onApply={(review, requestId) => applyConfigMutation.mutateAsync({ review, requestId })}
            onRenameSaved={(preset, name) => renameSavedConfigMutation.mutateAsync({ preset, name })}
            onDeleteSaved={(preset) => deleteSavedConfigMutation.mutateAsync(preset).then(() => undefined)}
            onCreateSavedInput={(input) => saveInputMutation.mutateAsync(input)}
            onCreateSavedDestination={(destination) => saveDestinationMutation.mutateAsync(destination)}
          />
          </div>
        ) : null}
        {activeTab === "diagnostics" ? (
          <DiagnosticsPanel
            diagnostics={diagnosticsQuery.data}
            logs={logsQuery.data}
            system={systemQuery.data}
            diagnosticsError={diagnosticsQuery.error instanceof Error ? diagnosticsQuery.error.message : null}
            logsError={logsQuery.error instanceof Error ? logsQuery.error.message : null}
            systemError={systemQuery.error instanceof Error ? systemQuery.error.message : null}
          />
        ) : null}
      </AppShell>
      {isAdminOpen ? (
        <AdminModal
          currentUser={meQuery.data.user}
          users={usersQuery.data}
          isLoading={usersQuery.isLoading}
          isSaving={createUserMutation.isPending || updateUserMutation.isPending}
          error={adminError ?? (usersQuery.error instanceof Error ? usersQuery.error.message : null)}
          onClose={() => {
            setAdminError(null);
            setIsAdminOpen(false);
          }}
          onCreateUser={(payload) => createUserMutation.mutateAsync(payload).then(() => undefined)}
          onUpdateUser={(userId, payload) => updateUserMutation.mutateAsync({ userId, payload }).then(() => undefined)}
        />
      ) : null}
      {isUpdateOpen ? (
        <UpdateModal
          status={updateStatusQuery.data}
          job={updateJobQuery.data}
          updateAvailable={updateAvailable}
          isChecking={checkUpdateMutation.isPending}
          isInstalling={installUpdateMutation.isPending}
          isPolling={updateJobQuery.isFetching || updateStatusQuery.data?.job_status === "running"}
          pollError={updatePollError}
          onClose={() => {
            setUpdatePollError(null);
            setIsUpdateOpen(false);
          }}
          onCheck={() => {
            void checkUpdateMutation.mutateAsync();
          }}
          onInstall={() => {
            void installUpdateMutation.mutateAsync();
          }}
        />
      ) : null}
    </>
  );
}
