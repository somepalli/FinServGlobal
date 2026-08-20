{{- define "compliance.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "compliance.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "compliance.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "compliance.labels" -}}
app.kubernetes.io/name: {{ include "compliance.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end }}

{{- define "compliance.selectorLabels" -}}
app.kubernetes.io/name: {{ include "compliance.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "compliance.image" -}}
{{- if not .repository }}{{ fail "image repository is required" }}{{ end }}
{{- if not (regexMatch "^sha256:[a-f0-9]{64}$" .digest) }}
{{- fail "images must use a sha256 digest" }}
{{- end }}
{{- printf "%s@%s" .repository .digest }}
{{- end }}

{{- define "compliance.apiServiceAccount" -}}
{{- printf "%s-api" (include "compliance.fullname" .) }}
{{- end }}

{{- define "compliance.webServiceAccount" -}}
{{- printf "%s-web" (include "compliance.fullname" .) }}
{{- end }}
